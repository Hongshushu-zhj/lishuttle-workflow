"""Desktop-only operations are isolated from Web routes and protected by runtime state."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'platform/backend'), str(ROOT / 'scripts')]
import core
import desktop_features as features
from runtime_paths import RuntimePaths
from project_config import ProjectStore


class DesktopFeaturesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.paths = RuntimePaths(ROOT, self.root, True)
        self.addCleanup(features.close)
        self.patches = [patch.object(features, 'resolve_paths', return_value=self.paths),
                        patch.object(core, 'ENV_FILE', str(self.paths.env_file))]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_preferences_are_desktop_only_and_revisioned(self):
        from server import ROUTES
        self.assertNotIn(('GET', 'desktop_preferences'), ROUTES)
        original = features.preferences_get({})
        saved = features.preferences_save({'values': {'onboarding_complete': True}, 'revision': original['revision']})
        self.assertTrue(saved['values']['onboarding_complete'])
        conflict = features.preferences_save({'values': {}, 'revision': original['revision']})
        self.assertEqual(conflict['code'], 'FILE_CONFLICT')
        self.assertTrue(self.paths.preferences_file.is_file())

    def test_busy_rejects_writes_and_does_not_create_preferences(self):
        with core.RUNTIME.operation('fixture operation'):
            # Operation context propagates on the same thread, so invoke as a separate request.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                response = pool.submit(features.preferences_save, {'values': {}, 'revision': 'x'}).result()
        self.assertEqual(response['code'], 'RUNTIME_BUSY')
        self.assertFalse(self.paths.preferences_file.exists())

    def test_scan_validation_and_unknown_id_are_structured(self):
        self.assertEqual(features.discover_start({'roots': []})['code'], 'INVALID_INPUT')
        self.assertEqual(features.discover_status({'id': ['missing']})['code'], 'INVALID_INPUT')
        response = features.discover_start({'roots': [str(self.root)]})
        self.assertIn('id', response)
        self.assertEqual(features.discover_status({'id': [response['id']]})['id'], response['id'])

    def test_stale_project_blocks_import_and_preserves_configuration(self):
        ProjectStore(self.paths.env_file).select(str(self.root / 'current'))
        response = features.legacy_apply({'source_root': str(self.root / 'source'), 'token': 'x', '_project': 'wrong'})
        self.assertIn('项目已切换', response['error'])

    def test_legacy_routes_forward_explicit_mapping_in_preview_and_apply(self):
        source = self.root/'legacy'
        old, new = self.root/'old-engine', self.root/'new-engine'
        ProjectStore(source/'env/local-win.env').select(str(old))
        mapping = [{'from':str(old),'to':str(new)}]
        body = {'source_root':str(source),'path_mappings':mapping}
        preview = features.legacy_preview(body)
        self.assertEqual(preview['path_changes'][0]['new'],new.as_posix())
        stale = features.legacy_apply(dict(body,token=preview['token'],path_mappings=[]))
        self.assertEqual(stale['code'],'PREVIEW_STALE')
        saved = features.legacy_apply(dict(body,token=preview['token']))
        self.assertTrue(saved['ok'],saved)
        self.assertEqual(ProjectStore(self.paths.env_file).load()['PROJECT_DIR'],new.as_posix())
