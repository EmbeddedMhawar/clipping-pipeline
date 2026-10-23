# Official Agent Skills Research: Remotion (`remotion-dev/skills`) & HyperFrames (`heygen-com/hyperframes`)

- **Date:** 2026-10-23
- **Primary Sources Investigated:**
  - **Remotion Official Agent Skills:** [`remotion-dev/skills`](https://github.com/remotion-dev/skills) — commit `6c67adcd9cdbe6eb84d76342da89b225f9161cb2` (package version `4.0.538`)
  - **HyperFrames Repository & Agent Skills:** [`heygen-com/hyperframes`](https://github.com/heygen-com/hyperframes) — commit `3badc9bfa586d15311b498a0839ed2064906b883` (`skills-manifest.json` version `1`)
- **Local Pipeline Files Audited:**
  - [`docs/adr/0012-remotion-and-hyperframes-rendering-engine.md`](file:///home/mhawar/Work/clipping-pipeline/docs/adr/0012-remotion-and-hyperframes-rendering-engine.md)
  - [`scripts/clipping_assembly.py`](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_assembly.py)
  - [`scripts/clipping_captions.py`](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_captions.py)
  - [`scripts/clipping_vfx_sfx.py`](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_vfx_sfx.py)
  - [`skills/clipping-assembly/SKILL.md`](file:///home/mhawar/Work/clipping-pipeline/skills/clipping-assembly/SKILL.md)
  - [`skills/clipping-captions/SKILL.md`](file:///home/mhawar/Work/clipping-pipeline/skills/clipping-captions/SKILL.md)
  - [`skills/clipping-vfx-sfx/SKILL.md`](file:///home/mhawar/Work/clipping-pipeline/skills/clipping-vfx-sfx/SKILL.md)

---

## Executive Summary

Following [ADR-0012](file:///home/mhawar/Work/clipping-pipeline/docs/adr/0012-remotion-and-hyperframes-rendering-engine.md), our short-form clipping pipeline migrated from FilmCraft/EffectCraft to **Remotion** (Steps 4–6 assembly, captions, and composite rendering) and **HyperFrames** (Step 6 deterministic HTML/SVG/GSAP motion graphics overlays).

Both upstream ecosystems maintain official, production-tested Agent Skills repositories (`remotion-dev/skills` and `heygen-com/hyperframes/skills`) specifically designed to prevent LLM/codegen hallucinations and enforce deterministic rendering and live Studio interactivity.

Auditing our current code generators (`scripts/clipping_assembly.py`, `scripts/clipping_captions.py`, and `scripts/clipping_vfx_sfx.py`) against the upstream skill rules and runtime contracts revealed **7 critical HyperFrames contract violations** (which break deterministic frame seeking and `hyperframes render` execution) and **6 high-impact Remotion 4.0.538 / Studio interactivity gaps** (which prevent live timeline editing in Remotion Studio and violate `@remotion/captions` and `@remotion/media` contracts).

---

## Part 1: Remotion Official Agent Skills (`remotion-dev/skills`)

### 1.1 Repository Structure & Router Architecture

- **Source:** [`README.md`](https://github.com/remotion-dev/skills/blob/6c67adcd9cdbe6eb84d76342da89b225f9161cb2/README.md), [`skills/remotion-best-practices/SKILL.md`](https://github.com/remotion-dev/skills/blob/6c67adcd9cdbe6eb84d76342da89b225f9161cb2/skills/remotion-best-practices/SKILL.md)
- **Installation CLI:** `npx skills add remotion-dev/skills`
- **Architecture:** `remotion-dev/skills` ships **11 modular skills** plus an umbrella router skill (`remotion-best-practices`) that mirrors every topic sub-skill inside `skills/remotion-best-practices/remotion-*/REFERENCE.md`:

| Skill Name | Primary Scope | Key Files in `remotion-dev/skills/skills/` |
| :--- | :--- | :--- |
| `remotion-best-practices` | Master router skill indexing all sub-skills by task | `remotion-best-practices/SKILL.md`, `remotion-*/REFERENCE.md` |
| `remotion-create` | Scaffolding blank projects (`npx create-video@latest --yes --blank --no-tailwind`) & 1080p typography/layout budgets | `remotion-create/SKILL.md`, `video-layout.md`, `tailwind.md` |
| `remotion-markup` | Writing Remotion React components, media, timing, sequencing, effects, fonts, FFmpeg | `remotion-markup/SKILL.md` + 29 topic `.md` guides |
| `remotion-interactivity` | Making compositions editable in the Remotion Studio visual timeline & canvas with source-code writeback | `remotion-interactivity/SKILL.md`, `timeline-structure.md`, `inline-effects.md` |
| `remotion-captions` | `@remotion/captions` `Caption` schema, SRT parsing, Whisper WebGPU, `<BasicCaptions>` page rendering | `remotion-captions/SKILL.md`, `display-captions.md`, `import-srt-captions.md`, `transcribe-captions.md` |
| `remotion-studio` | Running & controlling the Remotion Studio preview server (`--no-open`, `--port`, `--force-new`, WebMCP) | `remotion-studio/SKILL.md` |
| `remotion-render` | Rendering MP4, WebM, ProRes 4444 with alpha, stills, and multi-frame contact verification | `remotion-render/SKILL.md`, `transparent-videos.md` |
| `remotion-multimedia` | Extracting duration/dimensions via Mediabunny (`media-parser`) | `remotion-multimedia/SKILL.md`, `get-video-duration.md`, `get-video-dimensions.md`, `get-audio-duration.md` |
| `remotion-maps` | Animated map routes (Mapbox, MapLibre, MapTiler, Cesium, Static Maps) | `remotion-maps/SKILL.md`, `techniques/*.md` |
| `remotion-saas` | Building SaaS video apps (`<Player>`, Lambda/Cloud Run, SSR) | `remotion-saas/SKILL.md`, `player.md`, `rendering.md`, `framework.md` |
| `remotion-docs` / `remotion-upgrade` | Searching `remotion.dev/llms.txt` & upgrading Remotion packages | `remotion-docs/SKILL.md`, `remotion-upgrade/SKILL.md` |

---

### 1.2 Authoritative Rules from `remotion-dev/skills`

#### Rule R1: Deterministic Frame-Driven Animations Only
- **Source:** [`skills/remotion-markup/SKILL.md`](https://github.com/remotion-dev/skills/blob/6c67adcd9cdbe6eb84d76342da89b225f9161cb2/skills/remotion-markup/SKILL.md#L22-L26), [`skills/remotion-markup/timing.md`](https://github.com/remotion-dev/skills/blob/6c67adcd9cdbe6eb84d76342da89b225f9161cb2/skills/remotion-markup/timing.md)
- All animations **must** be driven by `useCurrentFrame()` and scaled using `fps` from `useVideoConfig()`.
- **Forbidden:** CSS transitions (`transition: ...`), CSS `@keyframes`, Tailwind animation utilities (`animate-*`), or `requestAnimationFrame` — they cause flickering and non-deterministic multi-tab rendering.
- **Recommended Spring Presets (`timing.md`):**
  - Snappy UI / Pop-ins: `{ stiffness: 200, damping: 20 }`
  - Smooth, no bounce: `{ damping: 200 }`
  - Playful bounce: `{ damping: 8 }`

#### Rule R2: `@remotion/media` `<Video>` and `<Audio>` + Direct `trimBefore` / `durationInFrames` Props
- **Source:** [`skills/remotion-markup/embedding-videos.md`](https://github.com/remotion-dev/skills/blob/6c67adcd9cdbe6eb84d76342da89b225f9161cb2/skills/remotion-markup/embedding-videos.md), [`skills/remotion-markup/audio.md`](https://github.com/remotion-dev/skills/blob/6c67adcd9cdbe6eb84d76342da89b225f9161cb2/skills/remotion-markup/audio.md), [`skills/remotion-markup/timing-props.md`](https://github.com/remotion-dev/skills/blob/6c67adcd9cdbe6eb84d76342da89b225f9161cb2/skills/remotion-markup/timing-props.md), [`skills/remotion-markup/video-editing.md`](https://github.com/remotion-dev/skills/blob/6c67adcd9cdbe6eb84d76342da89b225f9161cb2/skills/remotion-markup/video-editing.md)
- Use `<Video>` and `<Audio>` from `@remotion/media` (installed via `npx remotion add @remotion/media`).
- **Use `trimBefore` and `durationInFrames` directly** on `<Video>`, `<Audio>`, `<Img>`, `<AnimatedImage>`, `<Gif>`, and `<Sequence>` instead of legacy `startFrom` / `endAt`.
- When trimming a `<Sequence>` that wraps a `<Video>`, put `trimBefore` and `durationInFrames` on the `<Sequence>` (or `<TransitionSeries.Sequence>`), which shifts children's internal timestamps back by `trimBefore` frames so both video and nested captions trim in lockstep:
  ```tsx
  <TransitionSeries.Sequence
    name="Cut 1"
    trimBefore={Math.round(1154.16 * fps)}
    durationInFrames={Math.round(2.43 * fps)}
  >
    <Video src={staticFile('source.mp4')} />
    <BasicCaptions captions={captions} />
  </TransitionSeries.Sequence>
  ```

#### Rule R3: Remotion Studio Interactivity & Source-Code Writeback
- **Source:** [`skills/remotion-interactivity/SKILL.md`](https://github.com/remotion-dev/skills/blob/6c67adcd9cdbe6eb84d76342da89b225f9161cb2/skills/remotion-interactivity/SKILL.md), [`skills/remotion-interactivity/timeline-structure.md`](https://github.com/remotion-dev/skills/blob/6c67adcd9cdbe6eb84d76342da89b225f9161cb2/skills/remotion-interactivity/timeline-structure.md), [`skills/remotion-interactivity/inline-effects.md`](https://github.com/remotion-dev/skills/blob/6c67adcd9cdbe6eb84d76342da89b225f9161cb2/skills/remotion-interactivity/inline-effects.md)
- Our pipeline ([ADR-0012](file:///home/mhawar/Work/clipping-pipeline/docs/adr/0012-remotion-and-hyperframes-rendering-engine.md)) relies on **Remotion Studio** as the live interactive companion during Steps 4–6 (`--launch-companion`). For Remotion Studio's visual timeline and canvas drag handles to read and write back to JSX source code, compositions must obey 6 structural rules:
  1. **No `.map()` loops over timeline items (`timeline-structure.md`):**
     - *"Do not generate timeline items from arrays or loops (`scenes.map(...)`), because the Studio cannot reorder, trim, or write back to individual items inside a loop. Write each `<Sequence>`, `<TransitionSeries.Sequence>`, or `<Track>` child directly in JSX."*
  2. **Use `<TransitionSeries>` for consecutive shots and `<Track name="...">` for independent overlay tracks (`timeline-structure.md`):**
     - Consecutive dialogue cuts belong in `<TransitionSeries>` with `<TransitionSeries.Sequence name="Cut 0" trimBefore={...} durationInFrames={...}>`.
     - Independent overlays (B-roll cutaways, SFX transients, hook cards) belong in `<Track name="V2 — B-Roll">`, `<Track name="V3 — VFX & Hooks">`, `<Track name="A3 — SFX">` with explicit `<Sequence from={...} durationInFrames={...}>`.
  3. **Use `Interactive.Div` / `Interactive.create()` for canvas-draggable elements (`remotion-interactivity/SKILL.md`):**
     - Replace `<div>` / `<Img>` with `<Interactive.Div description="Brand Watermark" style={{ left: ..., top: ..., width: ..., height: ... }}>` so the user can drag/resize overlays in the Remotion Studio canvas and have coordinates written directly back to `.tsx`.
  4. **Use individual CSS `scale`, `translate`, `rotate` properties instead of `transform` strings (`inline-effects.md`):**
     - Write `style={{ scale: 1.85, translate: '120px -40px' }}` instead of `style={{ transform: 'translate(120px, -40px) scale(1.85)' }}`.
     - When animating `scale` with `interpolate()`, pass `{ output: 'perceptual-scale' }` as the 4th option so scaling feels linear to the eye.
  5. **Keep `interpolate()` calls inline on `style` (`inline-effects.md`):**
     - Do not hoist `interpolate()` results into local variables if Studio needs to inspect/edit keyframes in the timeline.
  6. **Inline `defaultProps` on `<Composition>` without `as` assertions or spread (`remotion-interactivity/SKILL.md`):**
     - Keep `defaultProps={{ ... }}` as a direct inline object literal on `<Composition>` with `schema={myCompSchema}` so Studio's right-hand props sidebar can edit and persist values to `Root.tsx`.

#### Rule R4: `@remotion/captions` Strict Schema & Leading-Space Rule
- **Source:** [`skills/remotion-captions/SKILL.md`](https://github.com/remotion-dev/skills/blob/6c67adcd9cdbe6eb84d76342da89b225f9161cb2/skills/remotion-captions/SKILL.md), [`skills/remotion-captions/display-captions.md`](https://github.com/remotion-dev/skills/blob/6c67adcd9cdbe6eb84d76342da89b225f9161cb2/skills/remotion-captions/display-captions.md), [`skills/remotion-captions/import-srt-captions.md`](https://github.com/remotion-dev/skills/blob/6c67adcd9cdbe6eb84d76342da89b225f9161cb2/skills/remotion-captions/import-srt-captions.md)
- Every item in `captions.json` **must** conform to the `Caption` TypeScript interface from `@remotion/captions`:
  ```ts
  export type Caption = {
    text: string;
    startMs: number;
    endMs: number;
    timestampMs: number | null;
    confidence: number | null;
    pageBreakAfter?: boolean;
  };
  ```
- **Critical Whitespace Invariant (`display-captions.md` line 169):**
  - *"The captions are whitespace sensitive. You should include spaces in the `text` field before each word."*
  - When `createTikTokStyleCaptions({ captions, combineTokensWithinMilliseconds })` concatenates tokens into `page.tokens`, it joins `token.text` directly (`page.tokens.map(t => t.text)`). If tokens lack a leading space (`" word"`), words render glued together or require non-standard workarounds.
- **Cut-Synchronized Caption Placement (`display-captions.md` lines 40–66):**
  - When a video is trimmed or cut across multiple `<Sequence>` / `<TransitionSeries.Sequence>` blocks, placing `<BasicCaptions>` **inside** the same `<Sequence>` as `<Video>` with `trimBefore` and `durationInFrames` on the `<Sequence>` automatically aligns source-timestamp captions with trimmed video cuts without manual timestamp recalculation.

#### Rule R5: GPU/Canvas Blur Effects & Transparent Rendering
- **Source:** [`skills/remotion-markup/effects.md`](https://github.com/remotion-dev/skills/blob/6c67adcd9cdbe6eb84d76342da89b225f9161cb2/skills/remotion-markup/effects.md), [`skills/remotion-render/transparent-videos.md`](https://github.com/remotion-dev/skills/blob/6c67adcd9cdbe6eb84d76342da89b225f9161cb2/skills/remotion-render/transparent-videos.md), [`skills/remotion-render/SKILL.md`](https://github.com/remotion-dev/skills/blob/6c67adcd9cdbe6eb84d76342da89b225f9161cb2/skills/remotion-render/SKILL.md)
- **Gaussian Blur (`effects.md`):** `@remotion/effects/blur` provides `blur({ radius })` for `<Video effects={[blur({ radius: 45 })]} />` or `<CanvasImage>` using WebGL2 / WebGPU shaders.
- **Visual Frame Verification (`remotion-render/SKILL.md`):** Verify compositions before full render via:
  ```bash
  npx remotion render <composition-id> --frames=0,30,90 --image-format=png
  ```
- **Transparent Video Export (`transparent-videos.md`):**
  - Apple ProRes 4444 (for NLE import):
    ```bash
    npx remotion render <id> out.mov --image-format=png --pixel-format=yuva444p10le --codec=prores --prores-profile=4444
    ```
  - WebM VP9 with alpha (for browser/Remotion `<Video>` overlay):
    ```bash
    npx remotion render <id> out.webm --image-format=png --pixel-format=yuva420p --codec=vp9
    ```

---

## Part 2: HyperFrames Official Agent Skills (`heygen-com/hyperframes`)

### 2.1 Repository Structure & Skills Manifest

- **Source:** [`skills-manifest.json`](https://github.com/heygen-com/hyperframes/blob/3badc9bfa586d15311b498a0839ed2064906b883/skills-manifest.json), [`skills/hyperframes/SKILL.md`](https://github.com/heygen-com/hyperframes/blob/3badc9bfa586d15311b498a0839ed2064906b883/skills/hyperframes/SKILL.md)
- **Installation CLI:** `npx skills add heygen-com/hyperframes`
- **Skills Shipped (7 skills in `skills-manifest.json`):**

| Skill Name | Purpose | Key Files in `heygen-com/hyperframes/skills/` |
| :--- | :--- | :--- |
| `hyperframes` | Authoring HTML/SVG/GSAP/Lottie/Three.js/Canvas video compositions under the deterministic seek contract | `hyperframes/SKILL.md`, `references/{spec,format,motion,runtimes,overlays,captions,sound,film,look,story,storyboard,review}.md`, `references/types/vertical.md` |
| `hyperframes-cli` | Complete CLI reference (`init`, `preview`, `render`, `lint`, `validate`, `check`, `inspect`, `snapshots`, `beats`, `compare`) | `hyperframes-cli/SKILL.md`, `references/{preview-render,lint-validate-inspect,conventions,beats,doctor-browser}.md` |
| `hyperframes-registry` | Searching, installing, adapting, and publishing reusable community blocks | `hyperframes-registry/SKILL.md`, `references/{block-anatomy,finding-blocks,adapting-blocks}.md` |
| `media-use` | Audio mixing, LUFS metering, beat detection, sidechain ducking, LUT color grading, SFX library (`skills/media-use/audio/assets/sfx/*.wav`) | `media-use/SKILL.md`, `audio/references/*.md`, `references/*.md` |
| `remotion-to-hyperframes` | Translating Remotion TSX compositions into HyperFrames HTML compositions | `remotion-to-hyperframes/SKILL.md`, `references/api-map.md`, `scripts/lint_source.py` |
| `slideshow` | Turning static slide decks into narrated video compositions | `slideshow/SKILL.md`, `references/standalone-harness.md` |
| `figma` | Extracting Figma variables, nodes, and vector paths into animated HTML scenes | `figma/SKILL.md`, `scripts/verify-motion.mjs` |

---

### 2.2 The 12-Point HyperFrames Deterministic Render Contract

- **Source:** [`skills/hyperframes/SKILL.md`](https://github.com/heygen-com/hyperframes/blob/3badc9bfa586d15311b498a0839ed2064906b883/skills/hyperframes/SKILL.md#L12-L26), [`skills/hyperframes/references/format.md`](https://github.com/heygen-com/hyperframes/blob/3badc9bfa586d15311b498a0839ed2064906b883/skills/hyperframes/references/format.md), [`skills/hyperframes/references/runtimes.md`](https://github.com/heygen-com/hyperframes/blob/3badc9bfa586d15311b498a0839ed2064906b883/skills/hyperframes/references/runtimes.md), [`packages/core/src/compositionReadiness.ts`](https://github.com/heygen-com/hyperframes/blob/3badc9bfa586d15311b498a0839ed2064906b883/packages/core/src/compositionReadiness.ts)

HyperFrames renders HTML to video by seeking a headless Chromium page to each frame (`t = frameIndex / fps`), waiting for readiness, and capturing the frame. It does **not** record real-time browser playback. Therefore, every HyperFrames HTML composition **must** obey all 12 rules:

1. **Timed elements require `class="clip"`, `data-start`, and `data-duration`:**
   - Every timed element must have `class="clip"`, `data-start="<seconds>"`, and `data-duration="<seconds>"` (in seconds, visible over `[start, start + duration)`).
   - The root container `<div id="root" data-composition-id="<id>" data-start="0" data-duration="<sec>" data-width="1080" data-height="1920" data-fps="30">` declares the composition root.
2. **Every element inside `#root` must be `position: absolute` or `position: fixed`:**
   - Because the runtime toggles `display: none` on `.clip` elements outside their active window, flow-positioned siblings would reflow when a clip mounts/unmounts.
3. **GSAP timelines MUST be created `{ paused: true }` and registered on `window.__timelines["<composition-id>"]`:**
   - Every GSAP timeline must be created paused and registered under the exact `data-composition-id` of its composition or sub-composition:
     ```js
     window.__timelines = window.__timelines || {};
     const tl = gsap.timeline({ paused: true });
     // ... add tweens with explicit start times ...
     window.__timelines["hook-title-0-3s"] = tl;
     ```
   - **Never** call freestanding `gsap.to()` or `gsap.fromTo()` outside a registered paused timeline — freestanding tweens run on wall-clock time instead of seek time, triggering `missing_data_no_timeline` and `sweep_static` errors.
4. **Non-GSAP runtimes (Canvas 2D, Three.js, Lottie, Raw SVG) register a seek handler:**
   - Either set `window.__hf = { seek(t) { ... }, duration: <sec> }` (`skills/hyperframes/references/runtimes.md`) or listen for `window.addEventListener('hf-seek', (e) => { const t = e.detail; ... })`.
5. **No CSS `@keyframes`, no CSS `transition`, no CSS `transform` on an element GSAP transforms (`gsap_css_transform_conflict`):**
   - Setting `transform: translateX(-50%)` in CSS on an element that GSAP animates (`scale`, `y`, `x`, `rotation`) causes GSAP's inline matrix to clobber or conflict with the CSS transform. Center using a full-width flex container (`left: 0; right: 0; display: flex; justify-content: center;`) instead.
6. **Never animate transforms on the `.clip` element itself (`gsap_animates_clip_element`):**
   - Put `.clip` (`class="clip" data-start="..." data-duration="..."`) on an outer wrapper `<div>`, and animate transforms (`scale`, `y`, `x`, `rotation`) on an **inner child element** inside `.clip`.
7. **Always use `gsap.fromTo()` (not `gsap.from()` or `gsap.to()` without explicit start state) inside scenes:**
   - Because the host re-seeks scenes backward and forward across frames, start states must be defined inside `tl.fromTo(target, fromVars, toVars, position)`, not left implicit.
8. **Deterministic randomness only:**
   - `Math.random()` is forbidden during render (`non_deterministic_random` lint rule). Use a seeded PRNG (e.g., Mulberry32) so frame `N` produces identical particles/jitter across workers.
9. **Closed-form time math (`f(t)`):**
   - Never accumulate state across `seek(t)` calls (`pos += vel * dt`), because render workers seek out of order across parallel chunks.
10. **Viewport units (`vw`, `vh`, `vmin`, `vmax`) are forbidden (`viewport_units` lint rule):**
    - Studio preview embeds compositions inside scaled iframes; always use `px` or `%` relative to `#root`.
11. **CDN allowlist & `crossorigin="anonymous"`:**
    - Prefer `https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js` (or `3.15.0` per `packages/core/src/gsapCdn.ts`). All `<img src="https://...">`, `<video>`, and font links require `crossorigin="anonymous"` for WebGL `texImage2D` capture.
12. **Visual & Static Verification Gate (`npx hyperframes check`):**
    - Run `npx hyperframes check` (which executes L1 static lint + L2 headless browser layout/overflow audit + L3 frame sweep for `sweep_blank` and `sweep_static`) before full video render.

---

### 2.3 HyperFrames CLI Reference & Transparent Overlay Rendering

- **Source:** [`skills/hyperframes-cli/SKILL.md`](https://github.com/heygen-com/hyperframes/blob/3badc9bfa586d15311b498a0839ed2064906b883/skills/hyperframes-cli/SKILL.md), [`skills/hyperframes-cli/references/preview-render.md`](https://github.com/heygen-com/hyperframes/blob/3badc9bfa586d15311b498a0839ed2064906b883/skills/hyperframes-cli/references/preview-render.md), [`skills/hyperframes-cli/references/lint-validate-inspect.md`](https://github.com/heygen-com/hyperframes/blob/3badc9bfa586d15311b498a0839ed2064906b883/skills/hyperframes-cli/references/lint-validate-inspect.md)

#### Key CLI Commands & Flags:
- **Static + Browser Validation:**
  ```bash
  npx hyperframes lint <projectDir> --json
  npx hyperframes check <projectDir> --json
  ```
- **Render Command Signature (`preview-render.md` lines 102–134):**
  ```bash
  npx hyperframes render [dir] \
    --composition <path-to-html> \
    --output <output-path> \
    --format <mp4|webm|mov> \
    --fps <number> \
    --quality <draft|standard|high>
  ```
  - **Important:** The positional `[dir]` argument is the **project directory** (default `.`), **not** the HTML file path! Passing an HTML file as positional `[dir]` fails with `ENOTDIR` unless `-c` / `--composition <file.html>` is used.
  - **Transparent Overlay Formats (`preview-render.md` lines 122, 165–171):**
    - `--format mov`: Encodes Apple ProRes 4444 with alpha (`yuva444p10le`) when the root composition has a transparent background (`background: transparent`).
    - `--format webm`: Encodes VP9 with alpha (`yuva420p`) — directly playable inside Chromium / Remotion Studio's `<Video>` component!

---

## Part 3: Audit of Our Clipping Pipeline Against Official Skills

### 3.1 Critical Findings in `scripts/clipping_vfx_sfx.py` (HyperFrames Integration)

| # | Location in `scripts/clipping_vfx_sfx.py` | Violation of Official HyperFrames Contract | Impact |
| :--- | :--- | :--- | :--- |
| **HF-1** | [`synthesize_hyperframes_hook_html` (L331–338)](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_vfx_sfx.py#L331-L338) & [`synthesize_color_stab_pass` (L381–385)](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_vfx_sfx.py#L381-L385) | Calls freestanding `gsap.fromTo("#hook-badge", ...)` and `gsap.to("#stab", ...)` **without** creating `const tl = gsap.timeline({ paused: true })` and **without** registering `window.__timelines["<composition-id>"] = tl`. | Violates Contract Rule #3 (`missing_data_no_timeline`, `sweep_static`). HyperFrames cannot seek the animation per frame; renders static frames or times out after 45s. |
| **HF-2** | [`synthesize_hyperframes_hook_html` (L326–329)](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_vfx_sfx.py#L326-L329) & [`synthesize_color_stab_pass` (L378–380)](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_vfx_sfx.py#L378-L380) | Timed elements `#hook-badge` and `#stab` are missing `class="clip"`, and `#root` is missing `data-start="0"`. | Violates Contract Rule #1 (`skills/hyperframes/SKILL.md` L14). Runtime visibility resolver does not manage `.clip` lifecycle properly. |
| **HF-3** | [`synthesize_hyperframes_hook_html` (L314–315, L327, L332–335)](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_vfx_sfx.py#L314-L335) | `.hook-card` has CSS `transform: translateX(-50%)` AND is the timed clip element AND GSAP animates `scale` and `y` directly on `#hook-badge`. | Violates Contract Rules #5 & #6 (`gsap_css_transform_conflict` and `gsap_animates_clip_element` in `references/format.md` L146–147). Centering breaks when GSAP overwrites `transform`, and animating the `.clip` node itself fails `hyperframes lint`. |
| **HF-4** | [`synthesize_color_stab_pass` (L383)](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_vfx_sfx.py#L383) | Uses `gsap.to("#stab", { opacity: 0, ... })` relying on CSS `opacity: 1` instead of `tl.fromTo(...)`. | Violates Contract Rule #7 (`references/format.md` L69: *"Use `fromTo`, not `from`, inside a scene: the host re-seeks the scene each time it shows"*). |
| **HF-5** | [`synthesize_color_stab_pass` (L393–400)](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_vfx_sfx.py#L393-L400) | Runs `hyperframes render <hf_html> --output <out_path> --fps 30` (passing HTML file as positional `dir` and omitting `--composition` and `--format mov`). | Fails CLI argument parsing (`preview-render.md` L108–125) because positional argument is `[dir]`, not `--composition <file.html>`, and `--format mov` is required for ProRes 4444 alpha output. |
| **HF-6** | [`synthesize_hyperframes_hook_html` (L300–346)](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_vfx_sfx.py#L300-L346) & [`detect_vfx_sfx_cues` (L540–552)](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_vfx_sfx.py#L540-L552) | Generates `.hyperframes.html` for the 0–3s hook card without rendering it to a video (`.mov`/`.webm`), then injects `asset_path=str(hf_hook_html)` directly into `.remotion.json` media items with `"kind": "Movie"`. | Remotion's `<Video>` / `<OffthreadVideo>` cannot decode a `.html` file as a video stream! The hook HTML must be rendered via `hyperframes render` (with FFmpeg drawbox/drawtext or PNG fallback if Chromium/HyperFrames CLI is unavailable) to a transparent video (`.mov` / `.webm`) before mounting on Track V3. |
| **HF-7** | [`synthesize_hyperframes_hook_html` (L308)](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_vfx_sfx.py#L308) | Uses outdated `cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js`. | Official HyperFrames standardizes on `https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js` (or `3.15.0` in `packages/core/src/gsapCdn.ts`). |

---

### 3.2 High-Impact Findings in `scripts/clipping_assembly.py` & `scripts/clipping_captions.py` (Remotion Integration)

| # | Location in Pipeline Scripts | Discrepancy vs `remotion-dev/skills` (v4.0.538) | Impact |
| :--- | :--- | :--- | :--- |
| **RM-1** | [`scripts/clipping_captions.py` (`_parse_srt_to_caption_items`, L833–862)](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_captions.py#L833-L862) | Generates caption JSON objects without `timestampMs: number \| null` and `confidence: number \| null`, and strips leading spaces from word tokens (`text.strip()`). | Violates `@remotion/captions` `Caption` type (`skills/remotion-captions/SKILL.md` L22–28) and the leading-space requirement (`display-captions.md` L169). Passing `captions.json` to `createTikTokStyleCaptions()` causes TypeScript/runtime mismatches and missing inter-word spaces. |
| **RM-2** | [`scripts/clipping_assembly.py` (`generate_remotion_bundle`, L1248–1286)](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_assembly.py#L1248-L1286) | Renders timeline cuts inside `placedCuts.map((c, idx) => (<Sequence ...>))` loop instead of explicit authored JSX `<Sequence>` elements per cut. | Per `remotion-interactivity/timeline-structure.md` L81–84, Remotion Studio **cannot** reorder, trim, or write back edits to `<Sequence>` items inside a `.map()` loop. Unrolling the cuts into explicit JSX `<Sequence name="Cut 0 — ...">` nodes in `ClipComposition.tsx` unlocks full Studio timeline editing! |
| **RM-3** | [`scripts/clipping_assembly.py` (`generate_remotion_bundle`, L1095–1097, L1264)](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_assembly.py#L1095-L1097) | Uses CSS `transform: 'translate(...) scale(...)'` string instead of individual CSS `scale` and `translate` properties. | Per `remotion-interactivity/inline-effects.md` L24–54, Remotion Studio expects individual `scale` and `translate` CSS properties on `style` rather than composite `transform` strings. |
| **RM-4** | [`scripts/clipping_assembly.py` (`generate_remotion_bundle`, L1121–1124, L1260, L1322)](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_assembly.py#L1121-L1124) | Uses legacy `startFrom={cut.startFrom}` on `<OffthreadVideo>` / `<Audio>` instead of `trimBefore={cut.startFrom}` and `durationInFrames={cut.durationInFrames}`. | Official `remotion-markup/timing-props.md` and `video-editing.md` standardize on `trimBefore` and `durationInFrames` across `<Sequence>`, `<Video>`, and `<Audio>` in Remotion 4.0+. |
| **RM-5** | [`scripts/clipping_assembly.py` (`generate_remotion_bundle`, L992–1000)](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_assembly.py#L992-L1000) | `Root.tsx` passes `defaultProps={compositionData as any}` from an imported variable with an `as any` type assertion. | Per `remotion-interactivity/SKILL.md` L103–129, Studio cannot persist right-sidebar prop edits back to `Root.tsx` when `defaultProps` uses `as` type assertions or references an external variable instead of an inline object literal. |
| **RM-6** | [`scripts/clipping_assembly.py` (L741–777)](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_assembly.py#L741-L777) & [`scripts/clipping_vfx_sfx.py` (L702–735)](file:///home/mhawar/Work/clipping-pipeline/scripts/clipping_vfx_sfx.py#L702-L735) | Companion launch spawns `npx remotion studio` without `--no-open` when headless/automated or without documenting multi-frame CLI verification (`npx remotion render --frames=0,30,90 --image-format=png`). | Per `remotion-studio/SKILL.md` and `remotion-render/SKILL.md`, `--no-open` avoids unwanted browser tab popups when automated, and `--frames=0,30,90 --image-format=png` provides fast deterministic visual verification of layout, captions, and overlays. |

---

## Part 4: Concrete Code Fixes & Compliant Templates

### 4.1 Compliant HyperFrames 0–3s Hook Composition (`scripts/clipping_vfx_sfx.py`)

Below is the 100% contract-compliant template for `synthesize_hyperframes_hook_html`:
- Root `#root` has `data-composition-id="hook-title-0-3s" data-start="0" data-duration="..." data-width="1080" data-height="1920" data-fps="30"`.
- Outer wrapper `#hook-clip` has `class="clip" data-start="0" data-duration="..."` and uses full-width flexbox centering (`left: 0; right: 0; display: flex; justify-content: center;`) so there is **zero CSS `transform`** on the animated node (`gsap_css_transform_conflict` = 0).
- Inner child `#hook-card` is the target of GSAP transforms, so `.clip` is never animated directly (`gsap_animates_clip_element` = 0).
- GSAP timeline is created with `gsap.timeline({ paused: true })`, uses explicit `tl.fromTo(...)`, and registers `window.__timelines["hook-title-0-3s"] = tl;`.

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>HyperFrames Hook: {escaped_text}</title>
  <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js" crossorigin="anonymous"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body {
      width: 1080px;
      height: 1920px;
      background: transparent;
      overflow: hidden;
      font-family: 'Inter', 'Montserrat', 'Helvetica Neue', Arial, sans-serif;
    }
    #root {
      position: relative;
      width: 1080px;
      height: 1920px;
      background: transparent;
      overflow: hidden;
    }
    .hook-clip {
      position: absolute;
      top: 280px;
      left: 0;
      width: 1080px;
      display: flex;
      justify-content: center;
      pointer-events: none;
    }
    .hook-card {
      background: rgba(12, 12, 16, 0.92);
      border: 3px solid {accent_color};
      border-radius: 24px;
      padding: 28px 44px;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.65);
      text-align: center;
      max-width: 920px;
    }
    .hook-text {
      color: #FFFFFF;
      font-size: 56px;
      font-weight: 900;
      letter-spacing: -0.02em;
      line-height: 1.15;
      text-transform: uppercase;
    }
    .hook-accent {
      color: {accent_color};
    }
  </style>
</head>
<body>
  <div id="root" data-composition-id="hook-title-0-3s" data-start="0" data-duration="{duration_sec:.2f}" data-width="1080" data-height="1920" data-fps="30">
    <div id="hook-clip" class="clip hook-clip" data-start="0" data-duration="{duration_sec:.2f}" data-track-index="1">
      <div id="hook-card" class="hook-card">
        <div class="hook-text">{escaped_text}</div>
      </div>
    </div>
  </div>
  <script>
    window.__timelines = window.__timelines || {};
    const tl = gsap.timeline({ paused: true });
    tl.fromTo(
      "#hook-card",
      { scale: 0.72, opacity: 0, y: 40 },
      { scale: 1.0, opacity: 1, y: 0, duration: 0.28, ease: "back.out(1.7)" },
      0
    );
    tl.fromTo(
      "#hook-card",
      { scale: 1.0, opacity: 1, y: 0 },
      { scale: 0.92, opacity: 0, y: -20, duration: 0.22, ease: "power2.in" },
      {exit_delay:.2f}
    );
    window.__timelines["hook-title-0-3s"] = tl;
  </script>
</body>
</html>
```

### 4.2 Compliant HyperFrames Color Stab Composition & CLI Render (`scripts/clipping_vfx_sfx.py`)

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>HyperFrames Color Stab</title>
  <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js" crossorigin="anonymous"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body { width: 1080px; height: 1920px; background: transparent; overflow: hidden; }
    #root { position: relative; width: 1080px; height: 1920px; background: transparent; overflow: hidden; }
    .stab-clip { position: absolute; top: 0; left: 0; width: 1080px; height: 1920px; pointer-events: none; }
    .stab-flash {
      position: absolute; top: 0; left: 0; width: 1080px; height: 1920px;
      background: radial-gradient(circle, rgba(255,255,255,0.75) 0%, rgba(198,255,0,0.35) 100%);
      mix-blend-mode: screen;
    }
  </style>
</head>
<body>
  <div id="root" data-composition-id="color-stab" data-start="0" data-duration="{duration_sec:.2f}" data-width="1080" data-height="1920" data-fps="30">
    <div id="stab-clip" class="clip stab-clip" data-start="0" data-duration="{duration_sec:.2f}" data-track-index="1">
      <div id="stab-flash" class="stab-flash"></div>
    </div>
  </div>
  <script>
    window.__timelines = window.__timelines || {};
    const tl = gsap.timeline({ paused: true });
    tl.fromTo(
      "#stab-flash",
      { opacity: 1.0 },
      { opacity: 0.0, duration: {duration_sec:.2f}, ease: "power2.out" },
      0
    );
    window.__timelines["color-stab"] = tl;
  </script>
</body>
</html>
```

And the corrected CLI invocation in `scripts/clipping_vfx_sfx.py`:
```python
subprocess.run(
    [
        hf_bin,
        "render",
        str(hf_html.parent),
        "--composition",
        str(hf_html),
        "--output",
        str(out_path),
        "--format",
        "mov",
        "--fps",
        "30",
    ],
    check=True,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    timeout=30,
)
```

### 4.3 Compliant `@remotion/captions` Output (`scripts/clipping_captions.py`)

In `_parse_srt_to_caption_items` (`scripts/clipping_captions.py` lines 833–862):
- Include `timestampMs: int((start_ms + end_ms) // 2)` and `confidence: 1.0` on every item so it satisfies `Caption` from `@remotion/captions`.
- Preserve or prepend a single leading space on `text` (`f" {clean_text}"` after the first token or on all word tokens per `display-captions.md` line 169) while also keeping `cleanText` if needed by custom renderers.

### 4.4 Adopting the Upstream Skills in Our Workspace

To make both official skill sets available to agents working in `/home/mhawar/Work/clipping-pipeline`:
1. **Install or vendor key reference rules** via `npx skills add remotion-dev/skills` and `npx skills add heygen-com/hyperframes`, or cross-link this research document from:
   - [`skills/clipping-assembly/SKILL.md`](file:///home/mhawar/Work/clipping-pipeline/skills/clipping-assembly/SKILL.md)
   - [`skills/clipping-captions/SKILL.md`](file:///home/mhawar/Work/clipping-pipeline/skills/clipping-captions/SKILL.md)
   - [`skills/clipping-vfx-sfx/SKILL.md`](file:///home/mhawar/Work/clipping-pipeline/skills/clipping-vfx-sfx/SKILL.md)
2. **Enforce pre-render verification gates** in our pipeline scripts:
   - For Remotion bundles: `npx remotion render <composition-id> --frames=0,30,90 --image-format=png`
   - For HyperFrames HTML overlays: `npx hyperframes lint <dir> --json` / `npx hyperframes check <dir> --json`
