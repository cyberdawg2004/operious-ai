"use client";

import { useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import * as THREE from "three";

const SUBSTRATES = [
  "Boundary",
  "Coordination",
  "Governance",
  "Session",
  "Execution",
  "Supervisor",
  "Arbitration",
];

function Node({
  angle,
  radius,
  speed,
  offset,
}: {
  angle: number;
  radius: number;
  speed: number;
  offset: number;
}) {
  const ref = useRef<THREE.Mesh>(null!);
  const line = useMemo(() => {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(6), 3));

    const material = new THREE.LineBasicMaterial({
      color: "#2A5CAA",
      opacity: 0.3,
      transparent: true,
    });

    return new THREE.Line(geometry, material);
  }, []);

  useFrame(({ clock }) => {
    const t = clock.getElapsedTime();
    const a = angle + t * speed + offset;
    const x = Math.cos(a) * radius;
    const z = Math.sin(a) * radius;
    const y = Math.sin(t * 0.4 + offset) * 0.3;

    if (ref.current) {
      ref.current.position.set(x, y, z);
    }

    const position = line.geometry.getAttribute("position") as THREE.BufferAttribute;
    position.setXYZ(0, 0, 0, 0);
    position.setXYZ(1, x, y, z);
    position.needsUpdate = true;
  });

  return (
    <group>
      <mesh ref={ref}>
        <sphereGeometry args={[0.06, 8, 8]} />
        <meshStandardMaterial
          color="#A8882C"
          emissive="#A8882C"
          emissiveIntensity={0.6}
        />
      </mesh>
      <primitive object={line} />
    </group>
  );
}

function CenterVessel() {
  const ref = useRef<THREE.Mesh>(null!);

  useFrame(({ clock }) => {
    ref.current.rotation.y = clock.getElapsedTime() * 0.15;
    ref.current.rotation.x = Math.sin(clock.getElapsedTime() * 0.1) * 0.1;
  });

  return (
    <mesh ref={ref}>
      <icosahedronGeometry args={[0.7, 0]} />
      <meshStandardMaterial
        color="#2A5CAA"
        emissive="#2A5CAA"
        emissiveIntensity={0.15}
        wireframe
      />
    </mesh>
  );
}

function CameraRig() {
  useFrame(({ camera, mouse }) => {
    const nextX = camera.position.x + (mouse.x * 0.5 - camera.position.x) * 0.02;
    const nextY = camera.position.y + (mouse.y * 0.3 - camera.position.y) * 0.02;

    camera.position.set(nextX, nextY, camera.position.z);
    camera.lookAt(0, 0, 0);
  });

  return null;
}

function Scene() {
  const nodes = useMemo(
    () =>
      SUBSTRATES.map((_, i) => ({
        angle: (i / SUBSTRATES.length) * Math.PI * 2,
        radius: 1.4 + (i % 3) * 0.2,
        speed: 0.08 + i * 0.01,
        offset: i * 0.8,
      })),
    []
  );

  return (
    <>
      <ambientLight intensity={0.2} />
      <pointLight position={[0, 0, 0]} intensity={2} color="#2A5CAA" distance={5} />
      <CenterVessel />
      {nodes.map((n, i) => (
        <Node key={i} {...n} />
      ))}
      <CameraRig />
    </>
  );
}

export function GovernanceNetwork() {
  return (
    <div className="h-[420px] w-full md:h-[500px]">
      <Canvas
        camera={{ position: [0, 0, 4], fov: 45 }}
        gl={{ alpha: true, antialias: true }}
        style={{ background: "transparent" }}
      >
        <Scene />
      </Canvas>
    </div>
  );
}
