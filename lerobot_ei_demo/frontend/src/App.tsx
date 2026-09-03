import { useEffect, useState } from "react";
import { RobotTelemetry } from "./RobotTelemetry";

type Camera = { id: string; name: string; index: string; manual: boolean; selected: boolean };
type Session = { leader_port: string | null; follower_port: string | null; operation: string };

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error((await response.json()).detail ?? `Request failed: ${response.status}`);
  return response.json() as Promise<T>;
}

function App() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [ports, setPorts] = useState<string[]>([]);
  const [cameraSetupOpen, setCameraSetupOpen] = useState(false);
  const [status, setStatus] = useState("Loading booth setup...");
  const [busy, setBusy] = useState(false);

  async function loadSetup() {
    const [nextCameras, nextSession, nextPorts] = await Promise.all([
      request<Camera[]>("/api/cameras"), request<Session>("/api/session"), request<string[]>("/api/ports"),
    ]);
    setCameras(nextCameras); setSession(nextSession); setPorts(nextPorts);
    setStatus("Ready");
  }

  useEffect(() => { loadSetup().catch((error: Error) => setStatus(error.message)); }, []);

  const updateCamera = (id: string, patch: Partial<Camera>) =>
    setCameras((current) => current.map((camera) => camera.id === id ? { ...camera, ...patch } : camera));

  async function saveCameras() {
    setBusy(true);
    try {
      await request("/api/cameras", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cameras.map(({ name, index, selected }) => ({ name, index: Number(index), selected }))) });
      await loadSetup(); setStatus("Camera setup saved");
    } catch (error) { setStatus((error as Error).message); } finally { setBusy(false); }
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

  return <main>
    <header><div><div className="eyebrow">Arduino VENTUNO Q / Edge Impulse</div><h1>Make the arm see what you see.</h1><p>Prepare the SO-101, then move into a local robotics session. Perception stays on the VENTUNO Q while the arm remains responsive.</p></div><div className="device-mark">Dual-brain edge AI<strong>VENTUNO Q</strong></div></header>
    <section className="setup" aria-label="Robot setup">
      <label>Robot<select><option>SO-101 leader/follower</option></select></label>
      <label>Leader port<select value={session?.leader_port ?? ""} onChange={(event) => setSession(session ? { ...session, leader_port: event.target.value } : session)}>{ports.map((port) => <option key={port}>{port}</option>)}</select></label>
      <label>Follower port<select value={session?.follower_port ?? ""} onChange={(event) => setSession(session ? { ...session, follower_port: event.target.value } : session)}>{ports.map((port) => <option key={port}>{port}</option>)}</select></label>
    </section>
    <section className="camera-section" aria-label="Saved camera views"><h2>Saved camera views</h2>{savedCameras.length ? <div className="cameras">{savedCameras.map((camera) => <figure className="camera-card" key={camera.id}><img src={`/api/cameras/${encodeURIComponent(camera.id)}/stream`} alt={`${camera.name} live view`} /><figcaption>{camera.name}</figcaption></figure>)}</div> : <p className="muted">No saved cameras yet. Open camera setup to choose your views.</p>}</section>
    <RobotTelemetry active={operationActive} />
    <button type="button" onClick={() => setCameraSetupOpen((open) => !open)}>{cameraSetupOpen ? "Close camera setup" : "Set up cameras"}</button>
    {cameraSetupOpen && <section className="camera-section camera-setup" aria-label="Camera setup"><h2>Choose your camera views</h2><div className="cameras">{cameras.map((camera) => <figure className="camera-card" key={camera.id}><img src={`/api/cameras/${encodeURIComponent(camera.id)}/stream`} alt={`${camera.name} setup preview`} /><figcaption>OpenCV {camera.index}</figcaption><label className="camera-row"><input type="checkbox" checked={camera.selected} onChange={(event) => updateCamera(camera.id, { selected: event.target.checked })} /><input type="text" value={camera.name} maxLength={80} onChange={(event) => updateCamera(camera.id, { name: event.target.value })} /></label></figure>)}</div><button type="button" onClick={saveCameras} disabled={busy}>Save camera selection</button></section>}
    <section className="actions"><button type="button" onClick={toggleTeleoperation} disabled={busy || ports.length < 2}>{operationActive ? "Stop teleoperation" : "Start teleoperation"}</button><div className="status"><span className={operationActive ? "dot active" : "dot"}></span>{status}</div></section>
  </main>;
}

export default App;
