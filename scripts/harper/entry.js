import {LocalLinter, Dialect, createBinaryModuleFromUrl} from "harper.js";

const linters = {};
const binary = createBinaryModuleFromUrl(new URL("/harper/harper.wasm", location.href).href);

async function linter(dialect) {
  const d = Dialect[dialect] ?? Dialect.American;
  if (!linters[dialect]) {
    const l = new LocalLinter({binary, dialect: d});
    linters[dialect] = l.setup().then(() => l);
  }
  return linters[dialect];
}

// spans harper = unités UTF-16, comme les index d'une string JS
window.harper = {
  dialects: Object.keys(Dialect).filter((k) => isNaN(+k)),
  async check(text, dialect = "American") {
    const l = await linter(dialect);
    return (await l.lint(text)).map((x) => {
      const s = x.span();
      return {
        offset: s.start,
        length: s.end - s.start,
        message: x.message(),
        kind: x.lint_kind_pretty(),
        replacements: x.suggestions().map((g) => g.get_replacement_text()),
      };
    });
  },
};
