import { useEffect, useState } from "react";
import { RobotTelemetry } from "./RobotTelemetry";

type Camera = { id: string; name: string; index: string; manual: boolean; selected: boolean };
type Session = { leader_port: string | null; follower_port: string | null; operation: string };
type CalibrationStatus = { leader: boolean; follower: boolean };
type Architecture = { system: string; machine: string; architecture: string; label: string };
type EiProject = { id: number; name: string };
type EiExperiment = { id: number; name: string };
type EiTarget = { format: string; name: string; description: string; compatible: boolean };
type EiModel = { id: string; name: string; path: string; compatible: boolean };
type EiConfig = { api_key: string; project_id: number | null };
type CameraInference = { camera_id: string; model_id: string | null; enabled: boolean; confidence: number; status: string; error: string | null; inference_ms: number | null };
type InferenceStatus = { architecture: Architecture; models: EiModel[]; cameras: CameraInference[] };
type DownloadJob = { id: string; status: string; model: string | null; error: string | null };
type CalibrationRole = "leader" | "follower";
type RobotProfile = { name: string; leader_port: string; follower_port: string; cameras: Array<{ name: string; camera_index: number }> };
type CalibrationSession = { status: string; role: CalibrationRole | null; phase: string | null; positions: Record<string, number> | null; ranges: Record<string, { min: number; max: number }> | null; message: string; error: string | null };

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error((await response.json()).detail ?? `Request failed: ${response.status}`);
  return response.json() as Promise<T>;
}

const postJson = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

type CalibrationPanelProps = {
  role: CalibrationRole;
  setRole: (role: CalibrationRole) => void;
  session: Session | null;
  ports: string[];
  portFinderMessage: string;
  startPortScan: () => void;
  viewPort: () => void;
  selectPort: (role: CalibrationRole, port: string) => void;
  calibration: CalibrationStatus;
  importCalibration: (role: CalibrationRole, file: File | undefined) => void;
  state: CalibrationSession | null;
  start: () => void;
  action: (path: "/api/calibration/center" | "/api/calibration/finish" | "/api/calibration/stop") => void;
  mode: "new" | "edit";
  profileName: string;
  setProfileName: (name: string) => void;
  saveProfile: () => void;
  close: () => void;
  cameras: Camera[];
  cameraSetupOpen: boolean;
  setCameraSetupOpen: (value: boolean | ((prev: boolean) => boolean)) => void;
  updateCamera: (id: string, patch: Partial<Camera>) => void;
  saveCameras: () => void;
  busy: boolean;
};

function CalibrationPanel({ role, setRole, session, ports, portFinderMessage, startPortScan, viewPort, selectPort, calibration, importCalibration, state, start, action, mode, profileName, setProfileName, saveProfile, close, cameras, cameraSetupOpen, setCameraSetupOpen, updateCamera, saveCameras, busy }: CalibrationPanelProps) {
  const port = role === "leader" ? session?.leader_port : session?.follower_port;
  return <section className="calibration-panel setup-modal" aria-label="Robot setup and live calibration"><div className="modal-heading"><div><small>ROBOT WORKFLOW</small><h2>{mode === "new" ? "Add a new robot pair" : `Edit ${profileName || "robot"}`}</h2></div><span className="calibration-phase">{state?.phase ?? "idle"}</span><button type="button" className="secondary-button modal-close" onClick={close}>Close</button></div><div className="robot-profile-editor"><label>Robot name<input value={profileName} onChange={(event) => setProfileName(event.target.value)} placeholder="e.g. SO101" /></label><button type="button" onClick={saveProfile}>{mode === "new" ? "Save new robot" : "Update robot"}</button></div><div className="camera-setup-inline"><h2>Camera setup</h2><p className="config-note">Choose the views that should appear in the workspace.</p><button type="button" onClick={() => setCameraSetupOpen((open) => !open)}>{cameraSetupOpen ? "Close camera setup" : "Add cameras"}</button>{cameraSetupOpen && <><div className="camera-config-list">{cameras.map((camera) => <article className="camera-config-row" key={camera.id}><img src={`/api/cameras/${encodeURIComponent(camera.id)}/stream?preview=true`} alt={`${camera.name} preview`} /><div><label className="check-label"><input type="checkbox" checked={camera.selected} onChange={(event) => updateCamera(camera.id, { selected: event.target.checked })} />Use this camera</label><input className="camera-name-input" type="text" value={camera.name} maxLength={80} onChange={(event) => updateCamera(camera.id, { name: event.target.value })} aria-label={`Name for camera ${camera.index}`} /><span className="camera-index">OpenCV {camera.index}</span></div></article>)}</div><button type="button" onClick={saveCameras} disabled={busy}>Save camera setup</button></>}</div><div className="calibration-download-inline"><strong>Existing calibration files</strong><a className={calibration.leader ? "" : "disabled-link"} href={calibration.leader ? "/api/calibration/download/leader" : undefined} download>Download leader</a><a className={calibration.follower ? "" : "disabled-link"} href={calibration.follower ? "/api/calibration/download/follower" : undefined} download>Download follower</a></div><p className="config-note">Ports are saved to LeRobot's official path. Calibration disables torque and writes the official role-specific JSON only when you click Save calibration.</p><div className="port-finder"><strong>Find a port</strong><p>{portFinderMessage}</p><div><button type="button" onClick={startPortScan}>Start scan</button><button type="button" className="secondary-button" onClick={viewPort}>View port</button></div></div><div className="setup-grid"><label>Leader port<select value={session?.leader_port ?? ""} onChange={(event) => selectPort("leader", event.target.value)}><option value="">Select a port</option>{ports.map((item) => <option key={item}>{item}</option>)}</select></label><label>Follower port<select value={session?.follower_port ?? ""} onChange={(event) => selectPort("follower", event.target.value)}><option value="">Select a port</option>{ports.map((item) => <option key={item}>{item}</option>)}</select></label></div><div className="calibration-status setup-status"><span className={calibration.leader ? "ready" : "missing"}>Leader {calibration.leader ? "ready" : "missing"}</span><span className={calibration.follower ? "ready" : "missing"}>Follower {calibration.follower ? "ready" : "missing"}</span></div><div className="setup-grid"><label>Import leader calibration JSON<input type="file" accept="application/json,.json" onChange={(event) => importCalibration("leader", event.target.files?.[0])} /></label><label>Import follower calibration JSON<input type="file" accept="application/json,.json" onChange={(event) => importCalibration("follower", event.target.files?.[0])} /></label></div><label>Calibrate role<select value={role} onChange={(event) => setRole(event.target.value as CalibrationRole)} disabled={state?.status === "running"}><option value="follower">Follower</option><option value="leader">Leader</option></select></label><p className="config-note">Selected port: <strong>{port ?? "select it above"}</strong></p><div className="calibration-actions"><button type="button" onClick={start} disabled={!port || state?.status === "running"}>Start calibration</button><button type="button" onClick={() => action("/api/calibration/center")} disabled={state?.phase !== "center"}>Capture center</button><button type="button" onClick={() => action("/api/calibration/finish")} disabled={state?.phase !== "range"}>Save calibration</button><button type="button" className="secondary-button" onClick={() => action("/api/calibration/stop")} disabled={state?.status !== "running"}>Stop</button></div><p className="calibration-message">{state?.message ?? "Start a session to read encoder values."}</p>{state?.positions && <div className="encoder-table">{Object.entries(state.positions).map(([name, value]) => <span key={name}><b>{name}</b><strong>{value}</strong>{state.ranges?.[name] && <small>{state.ranges[name].min} - {state.ranges[name].max}</small>}</span>)}</div>}{state?.error && <p className="calibration-error">{state.error}</p>}<div className="manual-calibration"><strong>Manual LeRobot calibration</strong><p>Use the selected ports in the official CLI if you prefer the terminal workflow.</p><code>lerobot-calibrate --teleop.type=so101_leader --teleop.port={session?.leader_port ?? "LEADER_PORT"} --teleop.id={profileName || "SO101"}</code><code>lerobot-calibrate --robot.type=so101_follower --robot.port={session?.follower_port ?? "FOLLOWER_PORT"} --robot.id={profileName || "SO101"}</code></div><a href="https://huggingface.co/docs/lerobot/en/installation" target="_blank" rel="noreferrer">Open LeRobot installation guide</a></section>;
}

function App() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [ports, setPorts] = useState<string[]>([]);
  const [calibration, setCalibration] = useState<CalibrationStatus>({ leader: false, follower: false });
  const [robotProfiles, setRobotProfiles] = useState<RobotProfile[]>([]);
  const [robotProfileName, setRobotProfileName] = useState("");
  const [robotSetupMode, setRobotSetupMode] = useState<"new" | "edit">("edit");
  const [draftProfileName, setDraftProfileName] = useState("");
  const [cameraSetupOpen, setCameraSetupOpen] = useState(false);
  const [robotSetupOpen, setRobotSetupOpen] = useState(false);
  const [portBaseline, setPortBaseline] = useState<string[] | null>(null);
  const [portFinderMessage, setPortFinderMessage] = useState("Ready to scan serial ports.");
  const [calibrationRole, setCalibrationRole] = useState<CalibrationRole>("follower");
  const [calibrationSession, setCalibrationSession] = useState<CalibrationSession | null>(null);
  const [edgeImpulseApiKey, setEdgeImpulseApiKey] = useState("");
  const [edgeImpulseProject, setEdgeImpulseProject] = useState("");
  const [eiProjects, setEiProjects] = useState<EiProject[]>([]);
  const [eiExperiments, setEiExperiments] = useState<EiExperiment[]>([]);
  const [eiExperiment, setEiExperiment] = useState("");
  const [eiTargets, setEiTargets] = useState<EiTarget[]>([]);
  const [eiTarget, setEiTarget] = useState("");
  const [inference, setInference] = useState<InferenceStatus | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [status, setStatus] = useState("Loading booth setup...");
  const [busy, setBusy] = useState(false);

  async function loadSetup() {
    const [nextCameras, nextSession, nextPorts, nextCalibration, nextInference, nextEiConfig, nextProfiles] = await Promise.all([
      request<Camera[]>("/api/cameras"), request<Session>("/api/session"), request<string[]>("/api/ports"), request<CalibrationStatus>("/api/calibration/status"), request<InferenceStatus>("/api/inference/status"), request<EiConfig>("/api/edge-impulse/config"), request<RobotProfile[]>("/api/robot-profiles"),
    ]);
    setCameras(nextCameras); setSession(nextSession); setPorts(nextPorts); setCalibration(nextCalibration); setInference(nextInference);
    setEdgeImpulseApiKey(nextEiConfig.api_key); setEdgeImpulseProject(nextEiConfig.project_id ? String(nextEiConfig.project_id) : "");
    setRobotProfiles(nextProfiles); setRobotProfileName(nextProfiles[0]?.name ?? ""); setStatus("Ready");
  }

  useEffect(() => { loadSetup().catch((error: Error) => setStatus(error.message)); }, []);

  useEffect(() => {
    if (!robotSetupOpen) return;
    const refresh = () => refreshPorts().catch(() => undefined);
    const refreshCalibration = () => refreshCalibrationSession().catch(() => undefined);
    refresh();
    refreshCalibration();
    const interval = window.setInterval(refresh, 1000);
    const calibrationInterval = window.setInterval(refreshCalibration, 250);
    return () => { window.clearInterval(interval); window.clearInterval(calibrationInterval); };
  }, [robotSetupOpen]);

  useEffect(() => {
    const refreshInference = () => {
      request<InferenceStatus>("/api/inference/status")
        .then(setInference)
        .catch(() => undefined);
    };
    const interval = window.setInterval(refreshInference, 1000);
    return () => window.clearInterval(interval);
  }, []);

  async function connectEdgeImpulse() {
    setBusy(true);
    try {
      const projects = await postJson<EiProject[]>("/api/edge-impulse/projects", { api_key: edgeImpulseApiKey });
      setEiProjects(projects);
      const projectId = Number(edgeImpulseProject) || projects[0]?.id;
      if (projectId) {
        setEdgeImpulseProject(String(projectId));
        await request("/api/edge-impulse/config", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ api_key: edgeImpulseApiKey, project_id: projectId }) });
        await loadTargets(projectId);
      } else {
        await request("/api/edge-impulse/config", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ api_key: edgeImpulseApiKey }) });
      }
      setStatus(`Connected to Edge Impulse (${projects.length} projects)`);
    } catch (error) { setStatus((error as Error).message); } finally { setBusy(false); }
  }

  async function loadTargets(projectId: number) {
    const payload = await postJson<{ targets: EiTarget[]; impulses: EiExperiment[] }>("/api/edge-impulse/targets", { api_key: edgeImpulseApiKey, project_id: projectId });
    setEiExperiments(payload.impulses);
    setEiExperiment(payload.impulses[0] ? String(payload.impulses[0].id) : "");
    setEiTargets(payload.targets);
    setEiTarget(payload.targets.find((target) => target.compatible)?.format ?? "");
  }

  async function downloadModel() {
    setDownloading(true); setStatus("Building Edge Impulse deployment...");
    try {
      let job = await postJson<DownloadJob>("/api/edge-impulse/download", { api_key: edgeImpulseApiKey, project_id: Number(edgeImpulseProject), impulse_id: Number(eiExperiment), deployment_type: eiTarget });
      while (job.status === "running") {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        job = await request<DownloadJob>(`/api/edge-impulse/download/${job.id}`);
      }
      if (job.status === "error") throw new Error(job.error ?? "Download failed");
      setInference(await request<InferenceStatus>("/api/inference/status"));
      setStatus(`Downloaded ${job.model}`);
    } catch (error) { setStatus((error as Error).message); } finally { setDownloading(false); }
  }

  const assignmentFor = (cameraId: string) => inference?.cameras.find((entry) => entry.camera_id === cameraId);

  async function assignModel(cameraId: string, patch: Partial<CameraInference>) {
    const current = assignmentFor(cameraId);
    const body = {
      camera_id: cameraId,
      model_id: patch.model_id !== undefined ? patch.model_id : current?.model_id ?? null,
      enabled: patch.enabled !== undefined ? patch.enabled : current?.enabled ?? false,
      confidence: current?.confidence ?? 0.5,
    };
    if (!body.model_id) body.enabled = false;
    try {
      setInference(await postJson<InferenceStatus>("/api/inference/assign", body));
      setStatus(body.enabled ? `Inference enabled on ${cameraId}` : `Inference off on ${cameraId}`);
    } catch (error) { setStatus((error as Error).message); }
  }

  const updateCamera = (id: string, patch: Partial<Camera>) =>
    setCameras((current) => current.map((camera) => camera.id === id ? { ...camera, ...patch } : camera));

  async function saveCameras() {
    setBusy(true);
    try {
      await request("/api/cameras", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cameras.map(({ name, index, selected }) => ({ name, index: Number(index), selected }))) });
      setCameraSetupOpen(false);
      await loadSetup(); setStatus("Camera setup saved");
    } catch (error) { setStatus((error as Error).message); } finally { setBusy(false); }
  }

  async function selectPort(role: CalibrationRole, port: string) {
    if (!session) return;
    try {
      const next = await request<Session>("/api/session/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [`${role}_port`]: port }),
      });
      setSession(next);
      setStatus(`${role === "leader" ? "Leader" : "Follower"} port saved`);
    } catch (error) { setStatus((error as Error).message); }
  }

  async function selectRobotProfile(name: string) {
    if (!name) return;
    try {
      const result = await postJson<{ session: Session; cameras: Camera[] }>("/api/robot-profiles/select", { name });
      setRobotProfileName(name); setSession(result.session); setCameras(result.cameras); setStatus(`Loaded robot profile ${name}`);
    } catch (error) { setStatus((error as Error).message); }
  }

  function openEditRobot() {
    if (!robotProfileName) return;
    setDraftProfileName(robotProfileName); setRobotSetupMode("edit"); setRobotSetupOpen(true);
  }

  function openNewRobot() {
    setDraftProfileName(""); setRobotSetupMode("new"); setRobotSetupOpen(true);
  }

  async function saveRobotProfile() {
    const name = draftProfileName.trim();
    if (!name) { setStatus("Enter a robot name before saving"); return; }
    if (!session?.leader_port || !session.follower_port) { setStatus("Select both robot ports before saving"); return; }
    try {
      const profile = await postJson<RobotProfile>("/api/robot-profiles", { name, leader_port: session.leader_port, follower_port: session.follower_port, cameras: cameras.filter((camera) => camera.selected).map((camera) => ({ name: camera.name, camera_index: Number(camera.index), type: "opencv" })) });
      setRobotProfiles((current) => [...current.filter((item) => item.name !== profile.name), profile]);
      setRobotProfileName(profile.name); setDraftProfileName(profile.name); setRobotSetupMode("edit"); setStatus(`Saved robot profile ${profile.name}`);
    } catch (error) { setStatus((error as Error).message); }
  }

  function beginPortFinder() {
    setPortBaseline(ports);
    setPortFinderMessage("Disconnect one arm, then scan again.");
  }

  async function refreshPorts() {
    const currentPorts = await request<string[]>("/api/ports");
    setPorts(currentPorts);
    setSession((current) => current ? {
      ...current,
      leader_port: currentPorts.includes(current.leader_port ?? "") ? current.leader_port : null,
      follower_port: currentPorts.includes(current.follower_port ?? "") ? current.follower_port : null,
    } : current);
  }

  async function scanPortChange() {
    try {
      await refreshPorts();
      const currentPorts = await request<string[]>("/api/ports");
      if (!portBaseline) {
        setPortBaseline(currentPorts);
        setPortFinderMessage("Disconnect one arm, then scan again.");
        return;
      }
      const removed = portBaseline.filter((port) => !currentPorts.includes(port));
      setPortBaseline(null);
      setPortFinderMessage(removed.length === 1 ? `Disconnected port: ${removed[0]}` : removed.length === 0 ? "No port disappeared. Check the cable, then try again." : "More than one port disappeared. Reconnect and try one arm at a time.");
    } catch (error) { setPortFinderMessage((error as Error).message); }
  }

  async function importCalibration(role: CalibrationRole, file: File | undefined) {
    if (!file) return;
    try {
      const contents = await file.text();
      await request("/api/calibration/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role, contents }),
      });
      setCalibration(await request<CalibrationStatus>("/api/calibration/status"));
      setStatus(`${role === "leader" ? "Leader" : "Follower"} calibration imported`);
    } catch (error) { setStatus((error as Error).message); }
  }

  async function refreshCalibrationSession() {
    setCalibrationSession(await request<CalibrationSession>("/api/calibration/session"));
  }

  async function startCalibration() {
    const port = calibrationRole === "leader" ? session?.leader_port : session?.follower_port;
    if (!port) { setStatus("Select a port before starting calibration"); return; }
    try {
      setCalibrationSession(await postJson<CalibrationSession>("/api/calibration/start", { role: calibrationRole, port }));
    } catch (error) { setStatus((error as Error).message); }
  }

  async function calibrationAction(path: "/api/calibration/center" | "/api/calibration/finish" | "/api/calibration/stop") {
    try {
      setCalibrationSession(await request<CalibrationSession>(path, { method: "POST" }));
      if (path.endsWith("finish")) setCalibration(await request<CalibrationStatus>("/api/calibration/status"));
    } catch (error) { setStatus((error as Error).message); }
  }

  async function toggleTeleoperation() {
    setBusy(true);
    try {
      const next = session?.operation === "teleoperation"
        ? await request<Session>("/api/teleoperation/stop", { method: "POST" })
        : await request<Session>("/api/teleoperation/start", { method: "POST" });
      setSession(next); setStatus(next.operation === "teleoperation" ? "Teleoperation active" : "Teleoperation stopped");
    } catch (error) { setStatus((error as Error).message); } finally { setBusy(false); }
  }

  const savedCameras = cameras.filter((camera) => camera.selected);
  const operationActive = session?.operation === "teleoperation";
  const models = inference?.models ?? [];
  const architectureLabel = inference?.architecture.label ?? "unknown";

  return <main>
    <header><div><div className="brand-lockup" aria-label="Arduino, Edge Impulse, and LeRobot"><img src="/assets/arduino.svg" alt="Arduino" /><span>+</span><img src="/assets/edge-impulse.svg" alt="Edge Impulse" /><span>+</span><img className="lerobot-logo" src="/assets/lerobot.png" alt="LeRobot" /></div><h1>Teleoperated Arm</h1><p>Prepare the SO-101, then move into a local robotics session. Perception stays on the VENTUNO Q while the arm remains responsive.</p></div></header>
    <div className="app-layout">
      <aside className="config-panel" aria-label="Configuration">
        <div className="config-heading"><span>Configuration</span><small>LOCAL DEVICE</small></div>
        <section className="config-section"><h2>Robot setup</h2><label>Robot profile<select value={robotProfileName} onChange={(event) => selectRobotProfile(event.target.value)}>{robotProfiles.length === 0 && <option value="">No robots saved yet</option>}{robotProfiles.map((profile) => <option key={profile.name} value={profile.name}>{profile.name}</option>)}</select></label><div className="robot-setup-buttons"><button type="button" onClick={openEditRobot} disabled={!robotProfileName}>Edit {robotProfileName || "robot"}</button><button type="button" className="secondary-button" onClick={openNewRobot}>Add new robot</button></div><div className="calibration-status"><span className={calibration.leader ? "ready" : "missing"}>Leader {calibration.leader ? "calibrated" : "needs calibration"}</span><span className={calibration.follower ? "ready" : "missing"}>Follower {calibration.follower ? "calibrated" : "needs calibration"}</span></div></section>
        <section className="config-section">
          <h2>Edge Impulse</h2>
          <p className="config-note">Download <code>.eim</code> models for this device, then assign one per camera. Detected architecture: <strong>{architectureLabel}</strong>.</p>
          <label>API key<input type="password" value={edgeImpulseApiKey} onChange={(event) => setEdgeImpulseApiKey(event.target.value)} placeholder="Paste API key" autoComplete="off" /><span className="config-note">Stored locally in the device config.</span></label>
          <button type="button" onClick={connectEdgeImpulse} disabled={busy || !edgeImpulseApiKey}>Connect project</button>
          {eiProjects.length > 0 && <label>Project<select value={edgeImpulseProject} onChange={(event) => { setEdgeImpulseProject(event.target.value); loadTargets(Number(event.target.value)).catch((error: Error) => setStatus(error.message)); }}>{eiProjects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>}
          {eiExperiments.length > 0 && <label>Experiment<select value={eiExperiment} onChange={(event) => setEiExperiment(event.target.value)}>{eiExperiments.map((experiment) => <option key={experiment.id} value={experiment.id}>{experiment.name}</option>)}</select></label>}
          {eiTargets.length > 0 && <>
            <label>Deployment target<select value={eiTarget} onChange={(event) => setEiTarget(event.target.value)}>{eiTargets.map((target) => <option key={target.format} value={target.format} disabled={!target.compatible}>{target.name}{target.compatible ? "" : " — incompatible"}</option>)}</select></label>
            <button type="button" onClick={downloadModel} disabled={downloading || !eiTarget || !eiExperiment}>{downloading ? "Downloading..." : "Download model"}</button>
          </>}
          <div className="model-list">{models.length ? models.map((model) => <span key={model.id} className={model.compatible ? "model-chip" : "model-chip unavailable"} title={model.compatible ? model.id : `Not built for ${architectureLabel}`}>{model.name}</span>) : <span className="config-note">No models downloaded yet.</span>}</div>
        </section>
      </aside>
      <section className="camera-column" aria-label="Selected camera views"><section className="camera-section"><h2>Selected camera views</h2>{savedCameras.length ? <div className="cameras">{savedCameras.map((camera) => {
        const assignment = assignmentFor(camera.id);
        return <figure className="camera-card" key={camera.id}>
          <img src={`/api/cameras/${encodeURIComponent(camera.id)}/stream`} alt={`${camera.name} live view`} />
          <figcaption>{camera.name}</figcaption>
          <div className="camera-inference">
            <select value={assignment?.model_id ?? ""} onChange={(event) => assignModel(camera.id, { model_id: event.target.value || null })} aria-label={`Edge Impulse model for ${camera.name}`}>
              <option value="">No model</option>
              {models.map((model) => <option key={model.id} value={model.id} disabled={!model.compatible}>{model.name}{model.compatible ? "" : " — incompatible"}</option>)}
            </select>
            <div className="inference-control">
              <button className="inference-toggle" type="button" aria-pressed={assignment?.enabled ?? false} disabled={!assignment?.model_id} onClick={() => assignModel(camera.id, { enabled: !(assignment?.enabled ?? false) })}>{assignment?.enabled ? "Inference on" : "Inference off"}</button>
              <span className="inference-time">{assignment?.inference_ms != null ? `${assignment.inference_ms.toFixed(1)} ms` : "-- ms"}</span>
            </div>
            {assignment?.status === "error" && assignment.error && <p className="inference-error">{assignment.error}</p>}
          </div>
        </figure>;
      })}</div> : <p className="muted">No cameras selected yet. Open Add cameras to choose your views.</p>}</section></section>
      <section className="telemetry-column" aria-label="Live robot telemetry"><section className="actions"><button type="button" onClick={toggleTeleoperation} disabled={busy || ports.length < 2}>{operationActive ? "Stop teleoperation" : "Start teleoperation"}</button><div className="status"><span className={operationActive ? "dot active" : "dot"}></span>{status}</div></section><RobotTelemetry active={operationActive} /></section>
    </div>
    {robotSetupOpen && <CalibrationPanel role={calibrationRole} setRole={setCalibrationRole} session={session} ports={ports} portFinderMessage={portFinderMessage} startPortScan={beginPortFinder} viewPort={scanPortChange} selectPort={selectPort} calibration={calibration} importCalibration={importCalibration} state={calibrationSession} start={startCalibration} action={calibrationAction} mode={robotSetupMode} profileName={draftProfileName} setProfileName={setDraftProfileName} saveProfile={saveRobotProfile} close={() => setRobotSetupOpen(false)} cameras={cameras} cameraSetupOpen={cameraSetupOpen} setCameraSetupOpen={setCameraSetupOpen} updateCamera={updateCamera} saveCameras={saveCameras} busy={busy} />}
  </main>;
}

export default App;
