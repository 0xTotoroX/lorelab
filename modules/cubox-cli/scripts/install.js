// 从随包源码构建；不把自有 CLI 换成上游发行二进制。
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const root = path.resolve(__dirname, "..");
const version = require("../package.json").version;
const binDir = path.join(root, "bin");
const binary = path.join(binDir, "cubox-cli" + (process.platform === "win32" ? ".exe" : ""));

try {
  for (const source of ["go.mod", "go.sum", "main.go", "cmd", "internal"]) {
    if (!fs.existsSync(path.join(root, source))) {
      throw new Error(`Missing bundled source: ${source}`);
    }
  }
  fs.mkdirSync(binDir, { recursive: true });
  execFileSync("go", [
    "build", "-trimpath", "-ldflags",
    `-s -w -X github.com/OLCUBO/cubox-cli/cmd.Version=${version}`,
    "-o", binary, ".",
  ], { cwd: root, stdio: "inherit" });
  console.log(`cubox-cli ${version} built from bundled source`);
} catch (error) {
  console.error(`Failed to build cubox-cli from bundled source: ${error.message}`);
  console.error("Install Go matching go.mod, then retry from this complete component source. No release fallback is used.");
  process.exit(1);
}
