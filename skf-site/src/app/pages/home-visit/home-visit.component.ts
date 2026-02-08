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
  readonly rotateX = computed(() => Math.sin(this.progress() * Math.PI * 2) * 5);
  readonly zoomScale = computed(() => 0.9 + 0.6 * Math.sin(this.progress() * Math.PI));

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
  private baseCameraDistance = 1;
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
    this.renderer.toneMappingExposure = 1.5;

    this.scene = new THREE.Scene();

    this.camera = new THREE.PerspectiveCamera(36, 1, 0.001, 100);
    this.camera.position.set(0, 0.01, 0.06);
    this.camera.lookAt(0, 0, 0);

    // Lights — cinematic 3-point setup
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.7));

    const key = new THREE.DirectionalLight(0xffffff, 3.0);
    key.position.set(5, 8, 5);
    this.scene.add(key);

    const fill = new THREE.DirectionalLight(0xc8d8ff, 1.0);
    fill.position.set(-4, 3, -3);
    this.scene.add(fill);

    const rim = new THREE.DirectionalLight(0xf5be2d, 0.8);
    rim.position.set(0, 2, -6);
    this.scene.add(rim);

    // Extra top light for metallic paint highlights
    const top = new THREE.DirectionalLight(0xeef2ff, 1.2);
    top.position.set(0, 10, 0);
    this.scene.add(top);

    this.scene.add(new THREE.HemisphereLight(0x1a1a2e, 0x0d0d1a, 0.5));

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
        const box = new THREE.Box3().setFromObject(model);
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());
        model.position.sub(center);
        this.carGroup.add(model);

        const maxDim = Math.max(size.x, size.y, size.z);
        const fov = this.camera.fov * (Math.PI / 180);
        this.baseCameraDistance = ((maxDim / 2) / Math.tan(fov / 2)) * 1.1;
        this.camera.position.set(0, maxDim * 0.15, this.baseCameraDistance);
        this.camera.lookAt(0, 0, 0);
        this.camera.near = this.baseCameraDistance * 0.01;
        this.camera.far = this.baseCameraDistance * 20;
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

    // Apply rotation
    const yRad = THREE.MathUtils.degToRad(this.rotateY());
    const xRad = THREE.MathUtils.degToRad(this.rotateX());
    this.carGroup.rotation.set(xRad, yRad, 0);

    // Zoom
    const dist = this.baseCameraDistance / this.zoomScale();
    this.camera.position.setZ(dist);
    this.camera.lookAt(0, 0, 0);

    this.renderFrame();
  }

  private renderFrame(): void {
    if (!this.renderer) return;
    this.renderer.render(this.scene, this.camera);
  }
}
