import { defineConfig } from "vite";

export default defineConfig({
  build: {
    rolldownOptions: {
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
