from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = Path(
    r"F:\dev\koishi-resonance-columba-bot\external\resonance-columba-bot\src\data"
)
DEFAULT_TYPESCRIPT_MODULE = Path(r"F:\dev\koishi-app\node_modules\typescript")
DEFAULT_OUTPUT = PROJECT_ROOT / "resources" / "goods" / "ColumbaTradeData2026.json"

NODE_EXPORT_SCRIPT = r"""
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const args = JSON.parse(process.argv[1]);
const ts = require(args.typescriptModule);

function normalizeCityName(name) {
  if (name === "\u4e03\u53f7\u81ea\u7531\u6e2f") {
    return "7\u53f7\u81ea\u7531\u6e2f";
  }
  return name;
}

function normalize(value) {
  if (Array.isArray(value)) {
    return value.map(normalize);
  }
  if (value && typeof value === "object") {
    const out = {};
    for (const [key, inner] of Object.entries(value)) {
      const normalizedKey = normalizeCityName(key);
      out[normalizedKey] = typeof inner === "string" ? normalizeCityName(inner) : normalize(inner);
    }
    return out;
  }
  return typeof value === "string" ? normalizeCityName(value) : value;
}

function compileTs(filePath) {
  const source = fs.readFileSync(filePath, "utf8");
  return ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2019,
      esModuleInterop: true,
    },
  }).outputText;
}

function loadTs(filePath, injectedRequire) {
  const module = { exports: {} };
  const sandbox = {
    exports: module.exports,
    module,
    require: injectedRequire || (() => ({})),
    console,
  };
  vm.runInNewContext(compileTs(filePath), sandbox, { filename: filePath });
  return module.exports;
}

const sourceDir = args.sourceDir;
const data = loadTs(path.join(sourceDir, "data.ts"));
const prestige = loadTs(path.join(sourceDir, "prestige.ts"));
const events = loadTs(path.join(sourceDir, "event.ts"));
const playerConfig = loadTs(path.join(sourceDir, "..", "interfaces", "player-config.ts"), (id) => {
  if (id === "assert") {
    return require("assert");
  }
  if (id === "../data/data") {
    return data;
  }
  if (id === "../data/data-steam") {
    return {
      resonanceskills_default_steam: data.resonanceskills_default,
      role_resonanceskills_steam: data.role_resonanceskills,
    };
  }
  return {};
});
const productsById = {};
for (const [index, product] of data.products_default.entries()) {
  productsById[String(index + 1)] = product;
}
const cicies = loadTs(path.join(sourceDir, "cicies.ts"), (id) => {
  if (id === "resonance-data-columba/dist/columbabuild") {
    return {
      CITY_ATTACH_LIST: data.cityattachlist_default,
      PRODUCTS: productsById,
    };
  }
  if (id === "./products") {
    return { PRODUCTS: data.products_default };
  }
  return {};
});

const citySet = new Set(cicies.cityList || []);
for (const product of data.products_default || []) {
  for (const key of ["buyPrices", "buyLot", "sellPrices"]) {
    for (const city of Object.keys(product[key] || {})) {
      citySet.add(city);
    }
  }
}

const payload = normalize({
  schema_version: 1,
  source: {
    project: "resonance-columba-bot",
    data_dir: sourceDir,
  },
  cities: Array.from(citySet),
  city_belongs_to: data.cityattachlist_default,
  products: data.products_default,
  prestige_levels: prestige.PRESTIGES,
  resonance_skills: data.resonanceskills_default,
  default_roles: data.role_resonanceskills,
  default_player_config: playerConfig.BotConfig,
  default_player_config_no_return_bargain: playerConfig.BotConfigNoReturnBargain,
  events: events.EVENTS,
});

process.stdout.write(JSON.stringify(payload, null, 2));
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Export columba-bot trade data into project JSON.")
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--typescript-module", default=str(DEFAULT_TYPESCRIPT_MODULE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    typescript_module = Path(args.typescript_module)
    output_path = Path(args.output)
    if not source_dir.exists():
        raise FileNotFoundError(f"source dir not found: {source_dir}")
    if not typescript_module.exists():
        raise FileNotFoundError(f"typescript module not found: {typescript_module}")

    result = subprocess.run(
        [
            "node",
            "-e",
            NODE_EXPORT_SCRIPT,
            json.dumps(
                {
                    "sourceDir": str(source_dir),
                    "typescriptModule": str(typescript_module),
                },
                ensure_ascii=True,
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    payload = json.loads(result.stdout)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(output_path),
                "cities": len(payload.get("cities", [])),
                "products": len(payload.get("products", [])),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise
