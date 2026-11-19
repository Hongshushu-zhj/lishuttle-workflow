"""Explicit desktop import never mutates the selected legacy installation."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'platform/backend'), str(ROOT / 'scripts')]
from migration import LegacyImporter, PreferencesStore
from project_config import ProjectStore, atomic_json, project_id


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'legacy'
        self.source.mkdir()
        (self.source / 'env').mkdir()
        self.target = self.base / 'desktop'
        self.store = ProjectStore(self.target / 'env/local-win.env')
        self.source_store = ProjectStore(self.source / 'env/local-win.env')
        self.project = self.base / 'external-engine'
        self.project.mkdir()
        self.source_store.select(str(self.project))
        self.source_store.save({'MAP_ROOT': 'D:/old/maps', 'CMAKE': 'C:/tools/cmake.exe'})
        self.source_store.binding('fixture-key', {'city': 'a'})
        self.importer = LegacyImporter(self.store, self.target / 'maintenance-archives')

    def test_preview_and_apply_preserve_source_bytes_and_copy_bindings(self):
        before = {str(p): p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        preview = self.importer.preview(str(self.source))
        self.assertEqual(preview['summary']['projects'], 1)
        self.assertEqual(preview['summary']['bindings'], 1)
        result = self.importer.apply(str(self.source), preview['token'])
        self.assertTrue(result['ok'])
        self.assertEqual(self.store.load()['MAP_ROOT'], 'D:/old/maps')
        self.assertEqual(self.store.binding('fixture-key'), {'city': 'a'})
        self.assertEqual(self.store.select(self.base / 'new-engine')['MAP_ROOT'], 'D:/old/maps')
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.source.rglob('*') if p.is_file()})

    def test_stale_preview_checks_both_source_and_target(self):
        preview = self.importer.preview(str(self.source))
        self.source_store.save({'MAP_ROOT': 'changed'})
        with self.assertRaisesRegex(ValueError, '预览'):
            self.importer.apply(str(self.source), preview['token'])
        preview = self.importer.preview(str(self.source))
        self.store.select(str(self.base / 'other'))
        with self.assertRaisesRegex(ValueError, '预览'):
            self.importer.apply(str(self.source), preview['token'])

    def test_existing_profiles_and_machine_values_are_not_overwritten(self):
        self.store.select(str(self.project))
        self.store.save({'MAP_ROOT': 'keep', 'CMAKE': 'keep-cmake'})
        preview = self.importer.preview(str(self.source))
        self.assertTrue(preview['conflicts'])
        result = self.importer.apply(str(self.source), preview['token'])
        self.assertEqual(self.store.load()['MAP_ROOT'], 'keep')
        self.assertEqual(self.store.load()['CMAKE'], 'keep-cmake')
        self.assertTrue(Path(result['backup']).is_file())

    def test_unknown_newer_schema_and_empty_source_are_rejected(self):
        file = self.source / 'env/project-profiles.json'
        data = json.loads(file.read_text(encoding='utf-8'))
        data['version'] = 999
        atomic_json(file, data)
        with self.assertRaises(ValueError):
            self.importer.preview(str(self.source))
        with self.assertRaises(ValueError):
            self.importer.preview(str(self.base / 'missing'))

    def test_preferences_atomic_revision_and_unknown_keys(self):
        prefs = PreferencesStore(self.target / 'preferences.json')
        initial = prefs.read()
        saved = prefs.write({'onboarding_complete': True}, initial['revision'])
        self.assertTrue(saved['values']['onboarding_complete'])
        with self.assertRaisesRegex(ValueError, '变化'):
            prefs.write({'onboarding_complete': False}, initial['revision'])
        with self.assertRaises(ValueError):
            prefs.write({'unknown': 'value'}, saved['revision'])
        data = json.loads((self.target / 'preferences.json').read_text())
        data['schema_version'] = 99
        atomic_json(self.target / 'preferences.json', data)
        with self.assertRaisesRegex(ValueError, '版本'):
            prefs.read()

    def test_legacy_registry_only_projects_are_retained(self):
        other = self.base / 'registered-only'
        atomic_json(self.source / 'env/projects.json', {'projects': [str(other)]})
        preview = self.importer.preview(str(self.source))
        self.assertEqual(preview['summary']['projects'], 2)
        self.importer.apply(str(self.source), preview['token'])
        self.assertIn(other.as_posix(), self.store.paths(read_only=True))

    def test_corrupt_preferences_can_use_backup_but_newer_schema_cannot(self):
        prefs = PreferencesStore(self.target / 'preferences.json')
        first = prefs.write({'onboarding_complete': True}, prefs.read()['revision'])
        prefs.write({'compact_mode': True}, first['revision'])
        prefs.path.write_bytes(b'corrupted fixture')
        fallback = prefs.read()
        self.assertTrue(fallback['recovery']['available'])
        self.assertTrue(fallback['values']['onboarding_complete'])
        repaired = prefs.write({'log_follow': True}, fallback['revision'])
        self.assertNotIn('recovery', repaired)
        self.assertTrue(list(self.target.glob('preferences.json.corrupt-*')))

    def test_structurally_corrupt_preferences_recover_and_preserve_damaged_bytes(self):
        for index,damaged in enumerate(([],None,17,{'schema_version':1,'values':[]},{'schema_version':1,'values':None})):
            with self.subTest(damaged=damaged):
                prefs = PreferencesStore(self.target/f'preferences-{index}.json')
                first = prefs.write({'onboarding_complete':True},prefs.read()['revision'])
                prefs.write({'compact_mode':True},first['revision'])
                raw = json.dumps(damaged).encode('utf-8')
                prefs.path.write_bytes(raw)
                fallback = prefs.read()
                self.assertTrue(fallback['recovery']['available'])
                self.assertEqual(fallback['values'],{'onboarding_complete':True})
                repaired = prefs.write({'log_follow':True},fallback['revision'])
                self.assertEqual(repaired['values'],{'onboarding_complete':True,'log_follow':True})
                preserved = list(self.target.glob(prefs.path.name+'.corrupt-*'))
                self.assertEqual(len(preserved),1)
                self.assertEqual(preserved[0].read_bytes(),raw)

    def test_future_preference_schema_never_uses_an_older_backup_or_repairs(self):
        prefs = PreferencesStore(self.target/'future.json')
        first = prefs.write({'onboarding_complete':True},prefs.read()['revision'])
        prefs.write({'compact_mode':True},first['revision'])
        for values in ({},[],None):
            with self.subTest(values=values):
                raw = json.dumps({'schema_version':99,'values':values}).encode('utf-8')
                prefs.path.write_bytes(raw)
                with self.assertRaisesRegex(ValueError,'版本'):
                    prefs.read()
                with self.assertRaisesRegex(ValueError,'版本'):
                    prefs.write({'log_follow':True},first['revision'])
                self.assertEqual(prefs.path.read_bytes(),raw)
                self.assertEqual(list(self.target.glob('future.json.corrupt-*')),[])

    def test_structurally_corrupt_preference_backup_is_rejected_cleanly(self):
        prefs = PreferencesStore(self.target/'broken.json')
        prefs.path.parent.mkdir(parents=True)
        prefs.path.write_text('[]')
        for backup in (None,[],{'schema_version':1,'values':[]},{'schema_version':99,'values':{}}):
            with self.subTest(backup=backup):
                atomic_json(prefs.path.with_suffix('.json.bak'),backup)
                with self.assertRaisesRegex(ValueError,'损坏|版本'):
                    prefs.read()

    def test_imported_missing_artifact_is_unavailable_but_frozen_verdict_is_preserved(self):
        archive = self.source/'.lishuttle-runs/42'
        archive.mkdir(parents=True)
        (archive/'present.dat').write_bytes(b'checked fixture')
        record = dict(version=1,sid=42,status='done',context={'project':str(self.project)},
            archive={'dir':str(archive),'status':'complete','issues':[],'files':[
                {'status':'archived','archive_path':str(archive/'artifacts/missing.dat')},
                {'status':'archived','archive_path':str(archive/'present.dat')}]},
            result={'verdict':'success','artifacts':{'state':'confirmed'}})
        atomic_json(archive/'session.json',record)
        before = (archive/'session.json').read_bytes()
        importer = LegacyImporter(self.store,self.target/'maintenance-archives',self.target/'runs')
        preview = importer.preview(str(self.source),include_history=True)
        importer.apply(str(self.source),preview['token'],include_history=True)
        imported_path = next((self.target/'runs').glob('*/session.json'))
        imported = json.loads(imported_path.read_text(encoding='utf-8'))
        self.assertEqual(imported['result'],record['result'])
        self.assertEqual(imported['context'],record['context'])
        self.assertEqual(imported['archive']['status'],'incomplete')
        missing,present = imported['archive']['files']
        self.assertEqual((missing['status'],missing['archive_path']),('unavailable',''))
        self.assertTrue(imported['archive']['issues'])
        self.assertEqual(present['status'],'archived')
        self.assertEqual(Path(present['archive_path']).read_bytes(),b'checked fixture')
        self.assertEqual((archive/'session.json').read_bytes(),before)

    def test_imported_missing_input_snapshot_marks_archive_incomplete(self):
        archive = self.source/'.lishuttle-runs/43'
        archive.mkdir(parents=True)
        record = dict(version=1,sid=43,status='done',context={'task_id':'7'},
            archive={'dir':str(archive),'status':'complete','files':[],'issues':[]},
            snapshots=[{'kind':'schema','archive_path':str(archive/'inputs/schema.xml')}],snapshot_issues=[],
            result={'verdict':'failed','issues':[{'code':'ORIGINAL_FAILURE'}]})
        atomic_json(archive/'session.json',record)
        importer = LegacyImporter(self.store,self.target/'maintenance-archives',self.target/'runs')
        preview = importer.preview(str(self.source),include_history=True)
        importer.apply(str(self.source),preview['token'],include_history=True)
        imported = json.loads(next((self.target/'runs').glob('*/session.json')).read_text(encoding='utf-8'))
        self.assertEqual(imported['result'],record['result'])
        self.assertEqual(imported['context'],record['context'])
        self.assertEqual(imported['archive']['status'],'incomplete')
        self.assertEqual(imported['snapshots'][0]['status'],'unavailable')
        self.assertEqual(imported['snapshots'][0]['archive_path'],'')
        self.assertTrue(imported['snapshot_issues'])

    def test_opt_in_history_preserves_evidence_and_uses_a_new_sid(self):
        archive = self.source / '.lishuttle-runs/42'
        archive.mkdir(parents=True)
        (archive / 'console.log').write_text('historical log\n', encoding='utf-8')
        record = dict(version=1, sid=42, status='done', context={'project': str(self.project)},
            archive={'dir': str(archive), 'files': [], 'status': 'complete'}, result={'verdict': 'success'})
        atomic_json(archive / 'session.json', record)
        importer = LegacyImporter(self.store, self.target / 'maintenance-archives', self.target / 'runs')
        plain = importer.preview(str(self.source))
        self.assertEqual(plain['summary']['history_sessions'], 0)
        preview = importer.preview(str(self.source), include_history=True)
        self.assertEqual(preview['summary']['history_sessions'], 1)
        result = importer.apply(str(self.source), preview['token'], include_history=True)
        self.assertEqual(result['imported']['history'], 1)
        directories = list((self.target / 'runs').iterdir())
        self.assertEqual(len(directories), 1)
        self.assertNotEqual(directories[0].name, '42')
        imported = json.loads((directories[0] / 'session.json').read_text(encoding='utf-8'))
        self.assertEqual(imported['imported_from']['sid'], 42)
        self.assertEqual(imported['archive']['dir'], str(directories[0]))
        self.assertEqual((directories[0] / 'console.log').read_text(), 'historical log\n')
        self.assertEqual(json.loads((archive / 'session.json').read_text())['sid'], 42)
        again = importer.preview(str(self.source), include_history=True)
        repeated = importer.apply(str(self.source), again['token'], include_history=True)
        self.assertEqual(repeated['imported']['history'], 0)

    def test_opt_in_history_checks_file_contents_against_preview(self):
        archive = self.source / '.lishuttle-runs/7'
        archive.mkdir(parents=True)
        atomic_json(archive / 'session.json', dict(version=1,sid=7,status='done',context={},archive={'dir':str(archive)}))
        (archive / 'console.log').write_text('old')
        importer = LegacyImporter(self.store, self.target / 'maintenance-archives', self.target / 'runs')
        preview = importer.preview(str(self.source), include_history=True)
        (archive / 'console.log').write_text('new')
        with self.assertRaisesRegex(ValueError, '预览'):
            importer.apply(str(self.source), preview['token'], include_history=True)

    def test_history_skips_malformed_metadata_and_existing_provenance(self):
        for sid,value in ((7,[]),(8,None)):
            directory = self.source/'.lishuttle-runs'/str(sid)
            directory.mkdir(parents=True)
            atomic_json(directory/'session.json',value)
        archive = self.source/'.lishuttle-runs/9'
        archive.mkdir()
        atomic_json(archive/'session.json',dict(version=1,sid=9,status='done',context={},archive={'dir':str(archive)}))
        existing = self.target/'runs/10'
        existing.mkdir(parents=True)
        atomic_json(existing/'session.json',{'imported_from':[]})
        importer = LegacyImporter(self.store,self.target/'maintenance-archives',self.target/'runs')
        preview = importer.preview(str(self.source),include_history=True)
        self.assertEqual(preview['summary']['history_sessions'],1)
        self.assertEqual(importer.apply(str(self.source),preview['token'],include_history=True)['imported']['history'],1)

    def test_explicit_prefix_relocation_rekeys_profiles_bindings_and_preserves_source(self):
        old = self.base
        new = self.base/'relocated'
        (new/'external-engine').mkdir(parents=True)
        self.source_store.save({'MAP_ROOT':str(old/'maps'),'CONFIG_SRC':str(old/'config'),
            'DLL_SRC':'ThirdPart/Dll','PRESET':str(old/'unstructured-preset'),'CMAKE':str(old/'tools/cmake.exe')})
        paths = [str(old/'tasks'),str(old/'tasks/engineering.csv'),str(old/'tasks/input.xml')]
        key = json.dumps([os.path.normcase(os.path.realpath(paths[0])),*paths[1:]],ensure_ascii=False)
        self.source_store.binding(key,{'engineering_file':paths[1],'schema_source':paths[2],
            'polygon_file':str(old/'area.txt'),'description':str(old/'keep-raw'),
            'path_overrides':{'MapPath':str(old/'maps/city'),'unknown':str(old/'do-not-rewrite')}})
        xml = self.source/'unrelated.xml'
        xml.write_text('<root>'+str(old)+'</root>',encoding='utf-8')
        before = {str(p):p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        mappings = [{'from':str(old),'to':str(new)}]
        preview = self.importer.preview(str(self.source),path_mappings=mappings)
        self.assertEqual(preview['projects'],[{'path':(new/'external-engine').as_posix(),'exists':True}])
        self.assertTrue(any(change['old']==str(old/'maps') and change['new']==(new/'maps').as_posix() for change in preview['path_changes']))
        self.assertTrue(all(set(change)=={'field','old','new','exists'} for change in preview['path_changes']))
        self.importer.apply(str(self.source),preview['token'],path_mappings=mappings)
        saved = self.store.load()
        self.assertEqual(saved['PROJECT_DIR'],(new/'external-engine').as_posix())
        self.assertEqual(saved['PROJECT_PROFILE_ID'],project_id(new/'external-engine'))
        self.assertEqual(saved['MAP_ROOT'],(new/'maps').as_posix())
        self.assertEqual(saved['CMAKE'],(new/'tools/cmake.exe').as_posix())
        self.assertEqual(saved['DLL_ROOT'],'ThirdPart/Dll')
        self.assertEqual(saved['DLL_SRC'],'')  # A valid preset determines the required mode.
        self.assertEqual(saved['PRESET'],str(old/'unstructured-preset'))
        new_key = json.dumps([os.path.normcase(os.path.realpath(new/'tasks')),
            str(new/'tasks/engineering.csv').replace('\\','/'),str(new/'tasks/input.xml').replace('\\','/')],ensure_ascii=False)
        binding = self.store.binding(new_key)
        self.assertEqual(binding['engineering_file'],(new/'tasks/engineering.csv').as_posix())
        self.assertEqual(binding['path_overrides']['MapPath'],(new/'maps/city').as_posix())
        self.assertEqual(binding['description'],str(old/'keep-raw'))
        self.assertEqual(binding['path_overrides']['unknown'],str(old/'do-not-rewrite'))
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.source.rglob('*') if p.is_file()})

    def test_prefix_relocation_matches_components_and_uses_one_longest_match(self):
        old = self.base
        new = old/'new'
        self.source_store.save({'MAP_ROOT':str(old/'maps'),'OUT_ROOT':str(self.project)+'-sibling/out'})
        mappings = [{'from':str(old),'to':str(new)}, {'from':str(new),'to':str(old/'chained')},
                    {'from':str(self.project),'to':str(old/'specific')}]
        preview = self.importer.preview(str(self.source),path_mappings=mappings)
        self.importer.apply(str(self.source),preview['token'],path_mappings=mappings)
        saved = self.store.load()
        self.assertEqual(saved['PROJECT_DIR'],(old/'specific').as_posix())
        self.assertEqual(saved['MAP_ROOT'],(new/'maps').as_posix())
        self.assertEqual(saved['OUT_ROOT'],(new/'external-engine-sibling/out').as_posix())

    def test_mapping_a_project_prefix_never_matches_a_sibling_or_rewrites_history(self):
        sibling = str(self.project)+'-sibling/maps'
        self.source_store.save({'MAP_ROOT':sibling})
        archive = self.source/'.lishuttle-runs/42'
        archive.mkdir(parents=True)
        context = {'project':str(self.project),'schema_path':str(self.project/'input.xml')}
        atomic_json(archive/'session.json',dict(version=1,sid=42,status='done',context=context,archive={'dir':str(archive)},result={'verdict':'success'}))
        mappings = [{'from':str(self.project).upper() if os.name=='nt' else str(self.project),'to':str(self.base/'moved')}]
        importer = LegacyImporter(self.store,self.target/'maintenance-archives',self.target/'runs')
        preview = importer.preview(str(self.source),True,path_mappings=mappings)
        importer.apply(str(self.source),preview['token'],True,path_mappings=mappings)
        self.assertEqual(self.store.load()['MAP_ROOT'],sibling)
        imported = json.loads(next((self.target/'runs').glob('*/session.json')).read_text(encoding='utf-8'))
        self.assertEqual(imported['context'],context)
        self.assertEqual(imported['result'],{'verdict':'success'})

    def test_changed_mappings_require_a_new_preview_even_without_matching_fields(self):
        first = [{'from':str(self.base/'unused'),'to':str(self.base/'new')}]
        preview = self.importer.preview(str(self.source),path_mappings=first)
        second = [{'from':str(self.base/'unused'),'to':str(self.base/'other')}]
        with self.assertRaisesRegex(ValueError,'预览'):
            self.importer.apply(str(self.source),preview['token'],path_mappings=second)

    def test_invalid_duplicate_and_colliding_relocations_are_rejected(self):
        valid = {'from':str(self.base/'old'),'to':str(self.base/'new')}
        for mappings in ('bad', [dict(valid,**{'from':'relative'})], [dict(valid,to='bad\npath')],
                         [valid,dict(valid)], [dict(valid,extra='x')], [valid]*17):
            with self.subTest(mappings=mappings),self.assertRaises(ValueError):
                self.importer.preview(str(self.source),path_mappings=mappings)
        second = self.base/'second-engine'
        self.source_store.select(str(second))
        mappings = [{'from':str(self.project),'to':str(self.base/'same')}, {'from':str(second),'to':str(self.base/'same')}]
        with self.assertRaisesRegex(ValueError,'冲突'):
            self.importer.preview(str(self.source),path_mappings=mappings)

    def test_relocated_source_keeps_an_existing_target_profile(self):
        destination = self.base/'existing'
        self.store.select(str(destination))
        self.store.save({'MAP_ROOT':'keep-target'})
        mappings = [{'from':str(self.project),'to':str(destination)}]
        preview = self.importer.preview(str(self.source),path_mappings=mappings)
        self.assertEqual(len(preview['conflicts']),1)
        self.importer.apply(str(self.source),preview['token'],path_mappings=mappings)
        self.assertEqual(self.store.load()['MAP_ROOT'],'keep-target')

    def test_mapping_to_a_drive_root_remains_absolute_and_from_root_keeps_suffix(self):
        self.source_store.save({'OUT_ROOT':str(self.project),'MAP_ROOT':str(self.project/'maps')})
        destination = self.project.anchor.replace('\\','/')
        mappings = [{'from':str(self.project),'to':destination}]
        preview = self.importer.preview(str(self.source),path_mappings=mappings)
        self.assertEqual(preview['projects'][0]['path'],destination)
        changed = {item['field'].rsplit('.',1)[-1]:item['new'] for item in preview['path_changes']}
        self.assertEqual(changed['OUT_ROOT'],destination)
        self.assertEqual(changed['MAP_ROOT'],destination+'maps')
        mappings = [{'from':destination,'to':str(self.base/'all-drive')}]
        preview = self.importer.preview(str(self.source),path_mappings=mappings)
        suffix = self.project.as_posix()[len(destination):]
        self.assertEqual(preview['projects'][0]['path'],(self.base/'all-drive').as_posix()+'/'+suffix)

    def test_mapping_rejects_binding_key_collisions_and_maps_absolute_build_paths(self):
        self.source_store.save({'BUILD_SUBDIR':str(self.base/'old/build'),'INSTALL_SUBDIR':str(self.base/'old/install')})
        original = str(self.base/'old')
        destination = str(self.base/'new')
        old_key = json.dumps([os.path.normcase(os.path.realpath(original)),original+'/a.csv',''])
        new_key = json.dumps([os.path.normcase(os.path.realpath(destination)),destination.replace('\\','/')+'/a.csv',''])
        self.source_store.binding(old_key,{'engineering_file':original+'/a.csv'})
        mappings = [{'from':original,'to':destination}]
        preview = self.importer.preview(str(self.source),path_mappings=mappings)
        fields = {item['field'].rsplit('.',1)[-1]:item['new'] for item in preview['path_changes']}
        self.assertEqual(fields['BUILD_SUBDIR'],(self.base/'new/build').as_posix())
        self.assertEqual(fields['INSTALL_SUBDIR'],(self.base/'new/install').as_posix())
        self.source_store.binding(new_key,{'engineering_file':destination.replace('\\','/')+'/a.csv'})
        with self.assertRaisesRegex(ValueError,'冲突'):
            self.importer.preview(str(self.source),path_mappings=mappings)

    def test_unreachable_unc_prefix_can_be_relocated_and_inaccessible_destination_is_false(self):
        old = '//SERVER/SHARE/Maps'
        new = self.base/'new-maps'
        self.source_store.save({'MAP_ROOT':old+'/city'})
        exists = Path.exists
        def denied(path):
            value = str(path).replace('\\','/').casefold()
            if value.startswith('//server/share/') or value.startswith(new.as_posix().casefold()):
                raise PermissionError(5,'Access is denied',str(path))
            return exists(path)
        mappings = [{'from':old,'to':str(new)}]
        with patch.object(Path,'exists',denied):
            preview = self.importer.preview(str(self.source),path_mappings=mappings)
            change = next(item for item in preview['path_changes'] if item['field'].endswith('.MAP_ROOT'))
            self.assertEqual(change,dict(field=change['field'],old=old+'/city',new=(new/'city').as_posix(),exists=False))
            self.importer.apply(str(self.source),preview['token'],path_mappings=mappings)
        self.assertEqual(self.store.load()['MAP_ROOT'],(new/'city').as_posix())
        self.assertEqual(self.source_store.load()['MAP_ROOT'],old+'/city')

    def test_known_regular_files_remain_invalid_mapping_prefixes(self):
        regular = self.base/'regular-file'
        regular.write_text('fixture')
        for mapping in ({'from':str(regular),'to':str(self.base/'new')},
                        {'from':str(self.base/'old'),'to':str(regular)}):
            with self.subTest(mapping=mapping),self.assertRaisesRegex(ValueError,'目录'):
                self.importer.preview(str(self.source),path_mappings=[mapping])
