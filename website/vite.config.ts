import { createReadStream, existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";

const websiteRoot = dirname(fileURLToPath(import.meta.url));
const generatedDataDirectory = resolve(websiteRoot, "data");

function generatedDataPlugin(): Plugin {
  return {
    name: "generated-commute-data",
    configureServer(server) {
      server.middlewares.use("/data", (request, response, next) => {
        const requestPath = decodeURIComponent((request.url ?? "/").split("?", 1)[0]);
        const candidate = resolve(generatedDataDirectory, `.${requestPath}`);
        if (
          !candidate.startsWith(`${generatedDataDirectory}${sep}`) ||
          !existsSync(candidate) ||
          !statSync(candidate).isFile()
        ) {
          next();
          return;
        }
        response.statusCode = 200;
        response.setHeader("Content-Type", "application/json; charset=utf-8");
        createReadStream(candidate).pipe(response);
      });
    },
    generateBundle() {
      for (const fileName of readdirSync(generatedDataDirectory)) {
        const sourcePath = join(generatedDataDirectory, fileName);
        if (statSync(sourcePath).isFile()) {
          this.emitFile({ type: "asset", fileName: `data/${fileName}`, source: readFileSync(sourcePath) });
        }
      }
    },
  };
}

export default defineConfig({
  // Relative assets work both at a GitHub Pages repository subpath and at /.
  base: "./",
  plugins: [generatedDataPlugin()],
  build: {
    rollupOptions: {
      input: {
        main: resolve(websiteRoot, "index.html"),
        methodology: resolve(websiteRoot, "methodology.html"),
      },
    },
  },
});
