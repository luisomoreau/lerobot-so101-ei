import { createElement, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import URDFManipulator from "urdf-loader/src/urdf-manipulator-element.js";

if (!customElements.get("urdf-viewer")) {
  customElements.define("urdf-viewer", URDFManipulator);
}

type JointSample = { type: "joint_update"; timestamp: number; joints: Record<string, number> };
const JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"];
const URDF_JOINTS = ["Rotation", "Pitch", "Elbow", "Wrist_Pitch", "Wrist_Roll", "Jaw"];
const LE_LAB_ASSETS = "https://cdn.jsdelivr.net/gh/huggingface/leLab@main/frontend/dist/so-101-urdf";

function useJointTelemetry(active: boolean) {
  const [samples, setSamples] = useState<JointSample[]>([]);
  useEffect(() => {
    if (!active) return;
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${window.location.host}/ws/joint-data`);
    socket.onmessage = (event) => {
      const sample = JSON.parse(event.data) as JointSample;
      setSamples((current) => [...current, sample].slice(-180));
    };
    return () => socket.close();
  }, [active]);
  return samples;
}

function RobotScene({ sample }: { sample?: JointSample }) {
  const viewerRef = useRef<HTMLElement & {
    setJointValue?: (name: string, value: number) => void;
    loadMeshFunc?: (path: string, manager: THREE.LoadingManager, material: THREE.Material, done: (mesh: THREE.Object3D | null, error?: Error) => void) => void;
    robot: THREE.Object3D | null;
    camera: THREE.PerspectiveCamera;
    controls: { target: THREE.Vector3; update: () => void };
    redraw: () => void;
  }>(null);
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    viewer.setAttribute("up", "Z");
    viewer.setAttribute("auto-redraw", "true");
    viewer.setAttribute("package", LE_LAB_ASSETS);
    viewer.loadMeshFunc = (path: string, manager: THREE.LoadingManager, material: THREE.Material, done: (mesh: THREE.Object3D | null, error?: Error) => void) => {
      const loader = new STLLoader(manager);
      const meshPath = path.replace("/so_arm_description/", "/");
      loader.load(meshPath, (geometry) => done(new THREE.Mesh(geometry, material)), undefined, (error) => done(null, error instanceof Error ? error : new Error(String(error))));
    };
    const fitViewer = () => {
      if (!viewer.robot) return;
      const bounds = new THREE.Box3().setFromObject(viewer.robot);
      const center = bounds.getCenter(new THREE.Vector3());
      const size = bounds.getSize(new THREE.Vector3());
      const distance = Math.max(size.x, size.y, size.z) * 0.6;
      viewer.camera.position.set(center.x + distance, center.y + distance, center.z + distance);
      viewer.controls.target.copy(center);
      viewer.controls.update();
      viewer.redraw();
    };
    viewer.addEventListener("geometry-loaded", fitViewer);
    viewer.setAttribute("urdf", `${LE_LAB_ASSETS}/urdf/so101_new_calib.urdf`);
    viewer.setAttribute("highlight-color", "#ff7657");
    return () => viewer.removeEventListener("geometry-loaded", fitViewer);
  }, []);
  useEffect(() => {
    const viewer = viewerRef.current;
    const values = sample?.joints ?? {};
    URDF_JOINTS.forEach((joint, index) => {
      const degrees = values[JOINTS[index]];
      if (degrees !== undefined) viewer?.setJointValue?.(joint, degrees * Math.PI / 180);
    });
  }, [sample]);
  return <div className="robot-scene" aria-label="Live SO-101 3D visualization">{createElement("urdf-viewer", { ref: viewerRef })}</div>;
}

function JointChart({ samples }: { samples: JointSample[] }) {
  const width = 720, height = 210, padding = 22;
  const points = JOINTS.map((joint) => samples.map((sample, index) => `${padding + index * ((width - padding * 2) / Math.max(samples.length - 1, 1))},${height / 2 - Math.max(-90, Math.min(90, sample.joints[joint] ?? 0)) * (height / 2 - padding) / 180}`).join(" "));
  const colors = ["#ff7657", "#ffd166", "#06d6a0", "#00c2c7", "#7ad7f0", "#f7f7f2"];
  return <div className="chart-wrap"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Joint encoder time series"><line x1={padding} x2={width - padding} y1={height / 2} y2={height / 2} className="chart-axis" />{points.map((line, index) => <polyline key={JOINTS[index]} points={line} fill="none" stroke={colors[index]} strokeWidth="2" />)}</svg><div className="legend">{JOINTS.map((joint, index) => <span key={joint} style={{ color: colors[index] }}>● {joint}</span>)}</div></div>;
}

export function RobotTelemetry({ active }: { active: boolean }) {
  const samples = useJointTelemetry(active);
  const latest = samples.at(-1);
  return <section className="telemetry-grid"><div><div className="panel-heading"><span>Live SO-101 model</span><small>{latest ? "STREAMING" : "WAITING FOR TELEMETRY"}</small></div><RobotScene sample={latest} /></div><div><div className="panel-heading"><span>Joint encoder timeline</span><small>{samples.length} samples</small></div><JointChart samples={samples} /></div></section>;
}
