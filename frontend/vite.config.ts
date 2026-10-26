import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";

export default defineConfig({
  build: {
    rolldownOptions: {
      input: {
        main: fileURLToPath(new URL("./index.html", import.meta.url)),
        research_session: fileURLToPath(new URL("./research/session.html", import.meta.url)),
        research_mask_editor: fileURLToPath(new URL("./research/mask-editor.html", import.meta.url)),
      },
      output: {
        codeSplitting: {
          groups: [
            { name: "three-core", test: /three[\\/]build[\\/]three\.core/ },
            { name: "three-webgl", test: /three[\\/]build[\\/]three\.module/ },
          ],
        },
      },
    },
  },
});
