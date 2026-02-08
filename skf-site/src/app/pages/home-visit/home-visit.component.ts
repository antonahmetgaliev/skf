import {
  AfterViewInit,
  Component,
  ElementRef,
  NgZone,
  OnDestroy,
  ViewChild,
  computed,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

const MODEL_PATH = 'models/acc-bmw-m4-gt3-evo/bmw-m4-gt3-evo.glb';

@Component({
  selector: 'app-home-visit',
  imports: [RouterLink],
  templateUrl: './home-visit.component.html',
  styleUrl: './home-visit.component.scss',
})
export class HomeVisitComponent implements AfterViewInit, OnDestroy {
  @ViewChild('pageWrap') private pageWrap?: ElementRef<HTMLElement>;
  @ViewChild('threeCanvas', { static: false }) private canvasRef?: ElementRef<HTMLCanvasElement>;

  /* ── public signals for template ── */
  readonly scrollY = signal(0);
  readonly progress = signal(0);
  readonly modelLoaded = signal(false);

  /** Parallax offset factors for each section (multiplied by scrollY) */
  readonly heroParallax = computed(() => `translateY(${this.scrollY() * 0.35}px)`);
  readonly aboutParallax = computed(() => `translateY(${this.scrollY() * 0.08}px)`);

  /** Car rotation driven by full-page scroll */
  readonly rotateY = computed(() => this.progress() * 360);
  readonly rotateX = computed(() => Math.sin(this.progress() * Math.PI * 2) * 3);
  readonly zoomScale = computed(() => 0.92 + 0.55 * Math.sin(this.progress() * Math.PI));

  readonly viewLabel = computed(() => {
    const y = ((this.rotateY() % 360) + 360) % 360;
    if (y < 30 || y >= 330) return 'Front';
    if (y < 60) return 'Front ¾';
    if (y < 120) return 'Side';
    if (y < 150) return 'Rear ¾';
    if (y < 210) return 'Rear';
    if (y < 240) return 'Rear ¾';
    if (y < 300) return 'Side';
    return 'Front ¾';
  });
  readonly angleDeg = computed(() => Math.round(this.rotateY() % 360));

  /* ── Three.js internals ── */
  private renderer!: THREE.WebGLRenderer;
  private scene!: THREE.Scene;
  private camera!: THREE.PerspectiveCamera;
  private carGroup = new THREE.Group();
  private groundMesh!: THREE.Mesh;
  private baseCameraDistance = 1;
  private modelBottomY = 0;
  private modelSize = new THREE.Vector3();
  private rafId: number | null = null;
  private resizeObserver?: ResizeObserver;

  constructor(private ngZone: NgZone) {}

  /* ────────── lifecycle ────────── */
  ngAfterViewInit(): void {
    if (typeof window === 'undefined') return;
    this.initThree();
    this.loadModel();
    window.addEventListener('scroll', this.onScroll, { passive: true });
    window.addEventListener('resize', this.onScroll);
    this.onScroll();
  }

  ngOnDestroy(): void {
    if (typeof window === 'undefined') return;
    window.removeEventListener('scroll', this.onScroll);
    window.removeEventListener('resize', this.onScroll);
    this.resizeObserver?.disconnect();
    if (this.rafId !== null) cancelAnimationFrame(this.rafId);
    this.renderer?.dispose();
  }

  /* ────────── Three.js ────────── */
  private initThree(): void {
    const canvas = this.canvasRef!.nativeElement;

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.3;

    // Enable shadow mapping for ground contact shadow
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    this.scene = new THREE.Scene();

    this.camera = new THREE.PerspectiveCamera(32, 1, 0.001, 200);
    this.camera.position.set(0, 0.01, 0.06);
    this.camera.lookAt(0, 0, 0);

    // Lights — natural studio / showroom lighting
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.4));

    // Main key light — slightly warm, from front-right above
    const key = new THREE.DirectionalLight(0xfff5e6, 2.2);
    key.position.set(6, 10, 6);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.near = 0.5;
    key.shadow.camera.far = 60;
    key.shadow.camera.left = -12;
    key.shadow.camera.right = 12;
    key.shadow.camera.top = 12;
    key.shadow.camera.bottom = -12;
    key.shadow.bias = -0.0005;
    key.shadow.normalBias = 0.02;
    this.scene.add(key);

    // Fill light — cool blue-ish from the left
    const fill = new THREE.DirectionalLight(0xb8cfe8, 0.6);
    fill.position.set(-5, 4, -2);
    this.scene.add(fill);

    // Rim light — warm gold accent from behind
    const rim = new THREE.DirectionalLight(0xf5be2d, 0.4);
    rim.position.set(-2, 3, -7);
    this.scene.add(rim);

    // Soft top/sky light
    const top = new THREE.DirectionalLight(0xe8eeff, 0.6);
    top.position.set(0, 12, 2);
    this.scene.add(top);

    // Hemisphere for natural ambient gradient (sky → ground)
    this.scene.add(new THREE.HemisphereLight(0x8899bb, 0x222222, 0.5));

    this.scene.add(this.carGroup);

    this.resizeCanvas();
    this.resizeObserver = new ResizeObserver(() => this.resizeCanvas());
    this.resizeObserver.observe(canvas.parentElement!);
  }

  private resizeCanvas(): void {
    const canvas = this.canvasRef?.nativeElement;
    if (!canvas) return;
    const w = window.innerWidth;
    const h = window.innerHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  private loadModel(): void {
    new GLTFLoader().load(
      MODEL_PATH,
      (gltf) => {
        const model = gltf.scene;

        // Enable shadow casting on all meshes
        model.traverse((child) => {
          if ((child as THREE.Mesh).isMesh) {
            child.castShadow = true;
            child.receiveShadow = true;
          }
        });

        const box = new THREE.Box3().setFromObject(model);
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());
        this.modelSize.copy(size);

        // Centre the model but keep it sitting ON the ground
        model.position.x = -center.x;
        model.position.y = -box.min.y; // bottom of car at y=0
        model.position.z = -center.z;
        this.modelBottomY = 0;

        this.carGroup.add(model);

        // ── Ground plane — subtle reflective surface ──
        const groundRadius = Math.max(size.x, size.z) * 3;
        const groundGeo = new THREE.CircleGeometry(groundRadius, 64);
        const groundMat = new THREE.MeshStandardMaterial({
          color: 0x111111,
          roughness: 0.55,
          metalness: 0.1,
          transparent: true,
          opacity: 0.6,
        });
        this.groundMesh = new THREE.Mesh(groundGeo, groundMat);
        this.groundMesh.rotation.x = -Math.PI / 2;
        this.groundMesh.position.y = 0;
        this.groundMesh.receiveShadow = true;
        this.scene.add(this.groundMesh);

        // ── Camera framing ──
        const maxDim = Math.max(size.x, size.y, size.z);
        const fov = this.camera.fov * (Math.PI / 180);
        this.baseCameraDistance = ((maxDim / 2) / Math.tan(fov / 2)) * 1.05;

        // Offset car to the RIGHT so left side of screen has room for text
        this.carGroup.position.x = maxDim * 0.35;

        // Camera slightly above, looking slightly down at the car
        const camY = maxDim * 0.22;
        this.camera.position.set(this.carGroup.position.x, camY, this.baseCameraDistance);
        this.camera.lookAt(this.carGroup.position.x, size.y * 0.25, 0);
        this.camera.near = this.baseCameraDistance * 0.01;
        this.camera.far = this.baseCameraDistance * 30;
        this.camera.updateProjectionMatrix();

        this.ngZone.run(() => this.modelLoaded.set(true));
        this.renderFrame();
      },
      undefined,
      (err) => console.error('GLTF load error:', err),
    );
  }

  /* ────────── scroll handler ────────── */
  private onScroll = (): void => {
    if (this.rafId !== null) return;
    this.rafId = requestAnimationFrame(() => {
      this.rafId = null;
      this.tick();
    });
  };

  private tick(): void {
    if (typeof window === 'undefined') return;

    const sy = window.scrollY;
    this.scrollY.set(sy);

    // Progress: 0→1 over the full page scroll
    const docH = document.documentElement.scrollHeight;
    const vh = window.innerHeight;
    const travel = Math.max(1, docH - vh);
    this.progress.set(Math.min(1, Math.max(0, sy / travel)));

    // Apply rotation around its own Y axis
    const yRad = THREE.MathUtils.degToRad(this.rotateY());
    const xRad = THREE.MathUtils.degToRad(this.rotateX());
    this.carGroup.rotation.set(xRad, yRad, 0);

    // Zoom — camera moves in/out along Z
    const dist = this.baseCameraDistance / this.zoomScale();
    const camY = this.modelSize.y * 0.22;
    this.camera.position.set(this.carGroup.position.x, camY, dist);
    this.camera.lookAt(this.carGroup.position.x, this.modelSize.y * 0.25, 0);

    this.renderFrame();
  }

  private renderFrame(): void {
    if (!this.renderer) return;
    this.renderer.render(this.scene, this.camera);
  }
}
