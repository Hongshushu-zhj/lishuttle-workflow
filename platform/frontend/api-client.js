/* api-client — plain script; shared application state is composed in app.js. */
"use strict";

async function api(name, body, method) {
  // build_status uses POST for project/revision context, but only discovers
  // executable state. A slow background query must not hold the mutation lock.
  const writing = method !== "GET" && name !== 'build_status';
  if (writing) S.pendingRequests = (S.pendingRequests || 0) + 1;
  const opt = method === "GET" ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...(body || {}), _project: S.project, _revision: S.profileRevision,
      _machine_revision: S.machineRevision }),
  };
  try {
    const suffix = method === 'GET' && S.project && name !== 'output' && name !== 'state'
      ? `${body ? '&' : '?'}_project=${encodeURIComponent(S.project)}&_revision=${encodeURIComponent(S.profileRevision || '')}` : '';
    const res = await fetch(`/api/${name}${method === "GET" ? body + suffix : ""}`, opt);
    const result = await res.json();
    if (result.code === 'RUNTIME_BUSY' && result.runtime) applyRuntimeState(result.runtime, true);
    return result;
  } finally {
    if (writing) S.pendingRequests--;
  }
}

const get = (name, qs) => api(name, qs ? `?${qs}` : "", "GET");
const post = (name, body) => api(name, body, "POST");
