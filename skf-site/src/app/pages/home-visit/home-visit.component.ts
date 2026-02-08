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
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';

const MODEL_PATH = 'models/acc-bmw-m4-gt3-evo/car-final.glb';

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
  private envMap!: THREE.Texture;
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
    this.renderer.toneMappingExposure = 1.4;

    // High-quality shadows
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    this.scene = new THREE.Scene();

    this.camera = new THREE.PerspectiveCamera(32, 1, 0.001, 200);
    this.camera.position.set(0, 0.01, 0.06);
    this.camera.lookAt(0, 0, 0);

    // ── Generate procedural studio environment map ──
    // Gives metallic paint and glossy surfaces realistic reflections
    this.envMap = this.createStudioEnvironment();
    this.scene.environment = this.envMap;

    // ── Lights — cinematic showroom rig ──

    // Ambient — very subtle, let env map handle most ambient
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.15));

    // KEY light — main illumination, warm white, front-right high
    const key = new THREE.DirectionalLight(0xfff8f0, 2.8);
    key.position.set(5, 8, 6);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.near = 0.5;
    key.shadow.camera.far = 60;
    key.shadow.camera.left = -15;
    key.shadow.camera.right = 15;
    key.shadow.camera.top = 15;
    key.shadow.camera.bottom = -15;
    key.shadow.bias = -0.0003;
    key.shadow.normalBias = 0.03;
    key.shadow.radius = 4;
    this.scene.add(key);

    // FILL light — cool blue from opposite side
    const fill = new THREE.DirectionalLight(0xb0c8e8, 0.8);
    fill.position.set(-6, 5, -3);
    this.scene.add(fill);

    // RIM / KICK light — gold accent from behind for edge separation
    const rim = new THREE.DirectionalLight(0xf5be2d, 0.6);
    rim.position.set(-3, 4, -8);
    this.scene.add(rim);

    // BOUNCE light — subtle warm from below to fill underbody shadows
    const bounce = new THREE.DirectionalLight(0xffeedd, 0.25);
    bounce.position.set(0, -2, 4);
    this.scene.add(bounce);

    // TOP softbox — broad overhead for roof/hood highlights
    const top = new THREE.DirectionalLight(0xf0f2ff, 1.0);
    top.position.set(1, 14, 1);
    this.scene.add(top);

    // Hemisphere — sky/ground ambient gradient
    this.scene.add(new THREE.HemisphereLight(0x7799cc, 0x111111, 0.4));

    this.scene.add(this.carGroup);

    this.resizeCanvas();
    this.resizeObserver = new ResizeObserver(() => this.resizeCanvas());
    this.resizeObserver.observe(canvas.parentElement!);
  }

  /** Create a procedural studio HDRI environment for realistic reflections */
  private createStudioEnvironment(): THREE.Texture {
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    pmrem.compileCubemapShader();

    // Build a simple scene that acts as a studio backdrop
    const envScene = new THREE.Scene();

    // Very dark sky dome — only provides subtle reflection highlights, not a visible bg
    const skyGeo = new THREE.SphereGeometry(50, 32, 16);
    const skyMat = new THREE.MeshBasicMaterial({ side: THREE.BackSide, vertexColors: true });
    const colors = new Float32Array(skyGeo.attributes['position'].count * 3);
    const pos = skyGeo.attributes['position'];
    for (let i = 0; i < pos.count; i++) {
      const y = (pos.getY(i) / 50 + 1) * 0.5; // 0 bottom → 1 top
      // Keep the dome very dark — just slight brightness at the top for reflections
      colors[i * 3]     = THREE.MathUtils.lerp(0.01, 0.08, y);
      colors[i * 3 + 1] = THREE.MathUtils.lerp(0.01, 0.09, y);
      colors[i * 3 + 2] = THREE.MathUtils.lerp(0.015, 0.12, y);
    }
    skyGeo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    envScene.add(new THREE.Mesh(skyGeo, skyMat));

    // Softbox panels — these create the highlight streaks on metallic paint
    // They only appear as reflections, not as visible scene elements
    const panelMat = (c: number) => new THREE.MeshBasicMaterial({ color: c, side: THREE.DoubleSide });

    // Top softbox — broad overhead
    const p1 = new THREE.Mesh(new THREE.PlaneGeometry(25, 8), panelMat(0x888888));
    p1.position.set(0, 15, 5);
    p1.lookAt(0, 0, 0);
    envScene.add(p1);

    // Right key — warm
    const p2 = new THREE.Mesh(new THREE.PlaneGeometry(5, 8), panelMat(0x665544));
    p2.position.set(18, 8, 3);
    p2.lookAt(0, 0, 0);
    envScene.add(p2);

    // Left fill — cool
    const p3 = new THREE.Mesh(new THREE.PlaneGeometry(5, 8), panelMat(0x445566));
    p3.position.set(-18, 8, 3);
    p3.lookAt(0, 0, 0);
    envScene.add(p3);

    const envMap = pmrem.fromScene(envScene, 0.04).texture;
    pmrem.dispose();
    return envMap;
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
    const loader = new GLTFLoader();

    // Set up Draco decoder for compressed meshes
    const dracoLoader = new DRACOLoader();
    dracoLoader.setDecoderPath('https://www.gstatic.com/draco/versioned/decoders/1.5.7/');
    dracoLoader.setDecoderConfig({ type: 'js' });
    loader.setDRACOLoader(dracoLoader);

    loader.load(
      MODEL_PATH,
      (gltf) => {
        dracoLoader.dispose(); // free decoder after load
        const model = gltf.scene;

        // Enable shadow casting on all meshes and ensure env map
        model.traverse((child) => {
          if ((child as THREE.Mesh).isMesh) {
            child.castShadow = true;
            child.receiveShadow = true;
            // Ensure PBR materials use the environment map
            const mat = (child as THREE.Mesh).material as THREE.MeshStandardMaterial;
            if (mat.isMeshStandardMaterial) {
              mat.envMap = this.envMap;
              mat.envMapIntensity = 1.0;
              mat.needsUpdate = true;
            }
          }
        });

        const box = new THREE.Box3().setFromObject(model);
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());
        this.modelSize.copy(size);

        console.log('Model bounds:', {
          min: box.min.toArray().map(v => v.toFixed(3)),
          max: box.max.toArray().map(v => v.toFixed(3)),
          size: size.toArray().map(v => v.toFixed(3)),
          center: center.toArray().map(v => v.toFixed(3)),
        });

        // Centre X/Z, and place wheels on the ground (y=0)
        model.position.x = -center.x;
        model.position.y = -box.min.y;
        model.position.z = -center.z;
        this.modelBottomY = 0;

        this.carGroup.add(model);

        // ── Soft contact shadow (radial gradient disc) ──
        // Shadow lives INSIDE the carGroup so it follows the car offset
        const groundRadius = Math.max(size.x, size.z) * 1.8;
        const groundGeo = new THREE.CircleGeometry(groundRadius, 64);

        // Create a tighter, darker radial gradient to anchor the car visually
        const gradSize = 512;
        const gradCanvas = document.createElement('canvas');
        gradCanvas.width = gradSize;
        gradCanvas.height = gradSize;
        const ctx = gradCanvas.getContext('2d')!;
        const gradient = ctx.createRadialGradient(
          gradSize / 2, gradSize / 2, 0,
          gradSize / 2, gradSize / 2, gradSize / 2,
        );
        gradient.addColorStop(0, 'rgba(0,0,0,0.85)');
        gradient.addColorStop(0.15, 'rgba(0,0,0,0.75)');
        gradient.addColorStop(0.35, 'rgba(0,0,0,0.45)');
        gradient.addColorStop(0.6, 'rgba(0,0,0,0.15)');
        gradient.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = gradient;
        ctx.fillRect(0, 0, gradSize, gradSize);
        const alphaMap = new THREE.CanvasTexture(gradCanvas);

        const groundMat = new THREE.MeshStandardMaterial({
          color: 0x000000,
          roughness: 0.5,
          metalness: 0,
          transparent: true,
          alphaMap,
          opacity: 1,
          depthWrite: false,
        });
        this.groundMesh = new THREE.Mesh(groundGeo, groundMat);
        this.groundMesh.rotation.x = -Math.PI / 2;
        this.groundMesh.position.y = 0.001; // just above zero to avoid z-fighting
        this.groundMesh.receiveShadow = true;
        this.carGroup.add(this.groundMesh); // add to carGroup so shadow follows the car

        // ── Camera framing ──
        const maxDim = Math.max(size.x, size.y, size.z);
        const fov = this.camera.fov * (Math.PI / 180);
        this.baseCameraDistance = ((maxDim / 2) / Math.tan(fov / 2)) * 1.05;

        // Offset car to the RIGHT so left side of screen has room for text
        this.carGroup.position.x = maxDim * 0.35;

        // Camera at wheel height, looking level at the car (reduces "floating" look)
        const camY = size.y * 0.35;
        this.camera.position.set(this.carGroup.position.x, camY, this.baseCameraDistance);
        this.camera.lookAt(this.carGroup.position.x, size.y * 0.35, 0);
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
    const camY = this.modelSize.y * 0.35;
    this.camera.position.set(this.carGroup.position.x, camY, dist);
    this.camera.lookAt(this.carGroup.position.x, this.modelSize.y * 0.35, 0);

    this.renderFrame();
  }

  private renderFrame(): void {
    if (!this.renderer) return;
    this.renderer.render(this.scene, this.camera);
  }
}
