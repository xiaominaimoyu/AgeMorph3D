# AgeMorph3D 项目指令

## 界面（UI）工作

- 任何界面改动（样式、布局、颜色、字体、组件、交互状态）开始前，先阅读根目录的 `DESIGN.md`，并以其中的视觉基础、组件与状态约定为准。
- 生产界面标记位于 `frontend/index.html`，其元素 id 是 `frontend/src/main.ts` 与 `frontend/tests/studio.spec.ts` 的契约。样式只有 `frontend/src/style.css`，由 `main.ts` 导入一次；断点、forced-colors 与减少动态效果规则都在该文件的 `@media` 块中。修改样式时优先复用已有变量（`--ink`、`--panel`、`--line`、`--text`、`--muted`、`--cyan`、`--amber`），不要另建一套重复的令牌；状态样式由 ARIA 属性与 `hidden` 驱动，不新增平行类名。
- 界面文字只保留控件名、读数与状态，不加标语、使用说明或英文副标签；需要解释才能看懂时改布局（见 `DESIGN.md`“主工作台”）。
- 若加入新的设计系统样式表（如 `system.css`），在入口只导入一次，保留其配套变量文件、字体与资源，并先与现有样式对照。
- 样式改动若与现有样式冲突，先向用户说明冲突，再做大范围改动。
- `design/` 目录是较早（2026-10-18）的设计方案，CSS 内联在 `design/index.html` 中，并使用 Google Fonts 远程字体，与 `DESIGN.md` 的"运行时不依赖远程字体或图片"冲突。未经用户确认，不要把其中的字体、配色或样式并入生产界面。
