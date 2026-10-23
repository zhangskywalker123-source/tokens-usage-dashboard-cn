'use strict';

const fs = require('node:fs');
const path = require('node:path');

const EXPECTED_CODEBURN_VERSION = '0.9.27';
const WINDOWS_HOME_MARKER = 'TOKENDASH_WINDOWS_KIMI_DESKTOP_HOME';
const MACOS_HOME_SUFFIX = '(home, "Library", "Application Support", "kimi-desktop", "daimon-share", "daimon", "runtime", "kimi-code", "home")';

function extendKimicodeHomes(source) {
  if (source.includes(WINDOWS_HOME_MARKER)) return source;
  const matches = ['join26', 'join43'].map(name => name + MACOS_HOME_SUFFIX).filter(call => source.includes(call));
  if (matches.length !== 1) {
    throw new Error('Pinned CodeBurn Kimi Code source no longer matches the verified patch anchor.');
  }
  const macosHome = matches[0];
  const joinFunction = macosHome.slice(0, macosHome.indexOf('('));
  const newline = String.fromCharCode(10);
  const windowsHome = joinFunction + '(process.env.APPDATA || ' + joinFunction + '(home, "AppData", "Roaming"), "kimi-desktop", "daimon-share", "daimon", "runtime", "kimi-code", "home")';
  const addition = [macosHome + ',', '    // ' + WINDOWS_HOME_MARKER, '    ' + windowsHome].join(newline);
  return source.replace(macosHome, addition);
}

function patchCodeburnKimicodeWindows(codeburnRoot) {
  const packagePath = path.join(codeburnRoot, 'package.json');
  const packageInfo = JSON.parse(fs.readFileSync(packagePath, 'utf8'));
  if (packageInfo.version !== EXPECTED_CODEBURN_VERSION) {
    throw new Error('Expected codeburn@' + EXPECTED_CODEBURN_VERSION + ', found ' + packageInfo.version);
  }
  let changedFiles = 0;
  for (const name of ['main.js', 'parse-worker.js']) {
    const workerPath = path.join(codeburnRoot, 'dist', name);
    const original = fs.readFileSync(workerPath, 'utf8');
    const patched = extendKimicodeHomes(original);
    if (patched !== original) {
      fs.writeFileSync(workerPath, patched, 'utf8');
      changedFiles++;
    }
  }
  return changedFiles;
}

if (require.main === module) {
  try {
    const codeburnRoot = process.argv[2];
    if (!codeburnRoot) throw new Error('Usage: node patch_codeburn_kimicode_windows.js <codeburn-package-dir>');
    const changedFiles = patchCodeburnKimicodeWindows(codeburnRoot);
    process.stdout.write(changedFiles ? 'Added Windows Kimi Desktop home to CodeBurn bundle files: ' + changedFiles : 'Windows Kimi Desktop home already present.');
    process.stdout.write(String.fromCharCode(10));
  } catch (error) {
    process.stderr.write(String(error && error.stack ? error.stack : error));
    process.stderr.write(String.fromCharCode(10));
    process.exitCode = 1;
  }
}

module.exports = { extendKimicodeHomes, patchCodeburnKimicodeWindows };
