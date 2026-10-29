import { readFileSync, writeFileSync } from "node:fs";
// 标准 Vite 产物保留，同时生成无需服务器或 CDN 的独立预览。
let html = readFileSync("dist/index.html", "utf8");
html = html.replace(
  /<script[^>]+src="([^"]+)"[^>]*><\/script>/g,
  (_, path) =>
    "<script>" +
    readFileSync("dist/" + path, "utf8").replace(/<\/script/gi, "<\\/script") +
    "</script>",
);
html = html.replace(
  /<link[^>]+href="([^"]+\.css)"[^>]*>/g,
  (_, path) => "<style>" + readFileSync("dist/" + path, "utf8") + "</style>",
);
// 脚本需要在 root 元素建立后执行。
const scripts = [...html.matchAll(/<script>[\s\S]*?<\/script>/g)]
  .map((x) => x[0])
  .join("");
html = html
  .replace(/<script>[\s\S]*?<\/script>/g, "")
  .replace("</body>", () => scripts + "</body>");
writeFileSync("dist/lorelab-settings.html", html);
console.log("独立配置台已构建：dist/lorelab-settings.html");
