# AgeMorph3D 项目指令

## 界面（UI）工作

- 任何界面改动（样式、布局、颜色、字体、组件、交互状态）开始前，先阅读根目录的 `DESIGN.md`，并以其中的视觉基础、组件与状态约定为准。
- 生产界面样式位于 `frontend/src/style.css`，由 `frontend/src/main.ts` 导入一次。`style.css` 通过 `@import` 引入 `responsive.css`，后者目前只含 forced-colors 无障碍规则；视口断点规则位于 `style.css` 自身的 `@media` 块中。修改样式时优先复用已有变量（`--ink`、`--panel`、`--line`、`--muted`、`--cyan`、`--amber`），不要另建一套重复的令牌。
- 若加入新的设计系统样式表（如 `system.css`），在入口只导入一次，保留其配套变量文件、字体与资源，并先与现有样式对照。
- 样式改动若与现有样式冲突，先向用户说明冲突，再做大范围改动。
- `design/` 目录是较早（2026-10-18）的设计方案，CSS 内联在 `design/index.html` 中，并使用 Google Fonts 远程字体，与 `DESIGN.md` 的"运行时不依赖远程字体或图片"冲突。未经用户确认，不要把其中的字体、配色或样式并入生产界面。
