/**
 * ESLint — chỉ nhằm bắt một loại bug: gọi hàm/biến chưa được định nghĩa.
 *
 * Vì sao cần: `apFetch is not defined` (Báo cáo tuần) là ReferenceError chỉ nổ
 * lúc chạy, trong nhánh catch, nên toàn bộ ~1440 test Python không thấy được.
 *
 * Vấn đề phải giải: các file trong static/js/ là **classic script**, không phải
 * ES module. Chúng dùng chung một global scope — sidebar_hubs.js gọi showToast()
 * định nghĩa trong dashboard.js là hợp lệ. ESLint xét từng file riêng nên sẽ báo
 * sai hàng loạt tham chiếu chéo file.
 *
 * Cách giải: dùng chính parser của ESLint (espree) đọc **top-level declaration**
 * của mọi file rồi khai báo chúng làm globals dùng chung. Danh sách này tự sinh
 * nên không bị lạc hậu khi thêm/xoá hàm — và quan trọng: tên nào không được khai
 * báo ở đâu (như apFetch) sẽ không có trong danh sách, nên vẫn bị bắt.
 */
import fs from "node:fs";
import path from "node:path";
import * as espree from "espree";
import globals from "globals";

const JS_DIR = "static/js";
const PARSER_OPTS = { ecmaVersion: 2023, sourceType: "script", loc: false };

/** Tên ở scope toàn cục của một classic script: khai báo top-level + window.X = ... */
function collectGlobalNames(code) {
  const names = new Set();
  const ast = espree.parse(code, PARSER_OPTS);

  const addPattern = (node) => {
    if (!node) return;
    switch (node.type) {
      case "Identifier":
        names.add(node.name);
        break;
      case "ObjectPattern":
        node.properties.forEach((p) =>
          addPattern(p.type === "RestElement" ? p.argument : p.value)
        );
        break;
      case "ArrayPattern":
        node.elements.forEach(addPattern);
        break;
      case "AssignmentPattern":
        addPattern(node.left);
        break;
      case "RestElement":
        addPattern(node.argument);
        break;
    }
  };

  for (const node of ast.body) {
    if (node.type === "FunctionDeclaration" || node.type === "ClassDeclaration") {
      if (node.id) names.add(node.id.name);
    } else if (node.type === "VariableDeclaration") {
      node.declarations.forEach((d) => addPattern(d.id));
    }
  }

  /*
   * `alias.foo = ...` tạo global `foo`. Alias không chỉ là `window`: i18n.js và
   * sidebar_hubs.js bọc trong IIFE `(function (global) { ... })(window)` rồi
   * export bằng `global.X = ...`. Nên phải lần ra tên tham số của IIFE trước.
   */
  const GLOBAL_OBJECTS = new Set(["window", "globalThis", "self"]);
  const aliases = new Set(GLOBAL_OBJECTS);

  /**
   * Đối tượng global có thể tới dưới nhiều dạng, không chỉ `window` trần. Cả
   * i18n.js và sidebar_hubs.js đóng bằng
   * `})(typeof window !== "undefined" ? window : globalThis);`
   * nên phải nhìn xuyên qua toán tử điều kiện và `||`.
   */
  const isGlobalExpr = (node) => {
    if (!node) return false;
    if (node.type === "ThisExpression") return true;
    if (node.type === "Identifier") return GLOBAL_OBJECTS.has(node.name);
    if (node.type === "ConditionalExpression")
      return isGlobalExpr(node.consequent) || isGlobalExpr(node.alternate);
    if (node.type === "LogicalExpression")
      return isGlobalExpr(node.left) || isGlobalExpr(node.right);
    return false;
  };

  const walk = (node, visit) => {
    if (!node || typeof node.type !== "string") return;
    visit(node);
    for (const key of Object.keys(node)) {
      const child = node[key];
      if (Array.isArray(child)) child.forEach((c) => walk(c, visit));
      else if (child && typeof child.type === "string") walk(child, visit);
    }
  };

  walk(ast, (node) => {
    if (node.type !== "CallExpression") return;
    const fn =
      node.callee.type === "FunctionExpression" ||
      node.callee.type === "ArrowFunctionExpression"
        ? node.callee
        : null;
    if (!fn) return;
    node.arguments.forEach((arg, i) => {
      const param = fn.params[i];
      if (!param || param.type !== "Identifier") return;
      if (isGlobalExpr(arg)) aliases.add(param.name);
    });
  });

  walk(ast, (node) => {
    if (
      node.type === "AssignmentExpression" &&
      node.left.type === "MemberExpression" &&
      !node.left.computed &&
      node.left.object.type === "Identifier" &&
      aliases.has(node.left.object.name) &&
      node.left.property.type === "Identifier"
    ) {
      names.add(node.left.property.name);
    }
  });

  return names;
}

const shared = {};
for (const file of fs.readdirSync(JS_DIR).filter((f) => f.endsWith(".js"))) {
  const code = fs.readFileSync(path.join(JS_DIR, file), "utf8");
  for (const name of collectGlobalNames(code)) shared[name] = "writable";
}

/** Thư viện nạp từ CDN trong index.html — không có source trong repo. */
const cdnLibs = {
  Chart: "readonly",
  ChartDataLabels: "readonly",
  Sortable: "readonly",
  html2canvas: "readonly",
  jspdf: "readonly",
  jsPDF: "readonly",
  XLSX: "readonly",
  tailwind: "writable",
};

export default [
  {
    files: ["static/js/**/*.js"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "script",
      globals: { ...globals.browser, ...cdnLibs, ...shared },
    },
    linterOptions: { reportUnusedDisableDirectives: true },
    rules: {
      "no-undef": "error",
    },
  },
];
