// What every browser test and tool needs from e2e/run_web_e2e.py, plus the files a customer may pick by mistake.
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

export const SHOP = process.env.E2E_SHOP_CODE!;
export const PDF = process.env.E2E_PDF!;
export const TEXT_FILE = process.env.E2E_TEXT_FILE!;
const PY = process.env.E2E_PYTHON!;
const SIM = process.env.E2E_SHOP_SIM!;

/** Plays the shop: `shop("approve", shortCode, SHOP)`, `shop("print", shortCode, SHOP)`. */
export const shop = (...args: string[]) => JSON.parse(execFileSync(PY, [SIM, ...args], { encoding: "utf8" }));

const dir = mkdtempSync(join(tmpdir(), "ap_web_e2e_"));
/** Builds a PDF with the same builders the API tests use (apps/api/tests/pdfs.py), e.g. pdf("blank(300)", "big.pdf"). */
export function pdf(expression: string, name: string): string {
  const path = join(dir, name);
  execFileSync(PY, ["-c", "import sys; sys.path.insert(0, sys.argv[1]); import pdfs; open(sys.argv[2], 'wb').write(eval('pdfs.' + sys.argv[3]))",
    join(dirname(SIM), "..", "apps", "api", "tests"), path, expression]);
  return path;
}

export const LOCKED = pdf("encrypted(2)", "locked.pdf");
export const EMPTY = join(dir, "empty.pdf");
export const BROKEN = join(dir, "broken.pdf");
writeFileSync(EMPTY, "");
writeFileSync(BROKEN, "this was a PDF once, before the download was cut short ".repeat(40));
