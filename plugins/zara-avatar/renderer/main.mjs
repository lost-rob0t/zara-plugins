// Zara's local VRM renderer host.
//
// Runs under Electron. Owns one BrowserWindow running app.mjs (Three.js +
// @pixiv/three-vrm) and speaks the zara-avatar stdio protocol with the
// plugin: newline-delimited JSON on stdin, responses and events on stdout.
// Local only; no network access is required or used.

import { app, BrowserWindow, ipcMain, protocol, net } from "electron";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createInterface } from "node:readline";
import process from "node:process";

// NixOS and similar setups cannot provide the Chrome SUID sandbox for a
// node_modules-downloaded Electron binary; without this switch the GPU and
// zygote processes crash-loop and the page never loads. This renderer is a
// local-only stdio surface with no network access, so the sandbox loss is
// acceptable.
app.commandLine.appendSwitch("no-sandbox");

const here = dirname(fileURLToPath(import.meta.url));
const AVATAR_SCHEME = "avatar";
const AVATAR_URL_PREFIX = `${AVATAR_SCHEME}://local/`;

let window = null;
let pageReady = false;
const pendingToPage = [];

function emit(document) {
  process.stdout.write(JSON.stringify(document) + "\n");
}

function sendToPage(document) {
  if (pageReady && window && !window.isDestroyed()) {
    window.webContents.send("avatar-command", document);
  } else {
    pendingToPage.push(document);
  }
}

function createWindow(options) {
  window = new BrowserWindow({
    width: options.width || 480,
    height: options.height || 720,
    transparent: Boolean(options.transparent),
    alwaysOnTop: Boolean(options.alwaysOnTop),
    frame: !options.transparent,
    backgroundColor: options.transparent ? "#00000000" : "#1a1a22",
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: join(here, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  window.setMenuBarVisibility(false);
  window.loadFile(join(here, "index.html"));
  window.on("closed", () => {
    window = null;
    pageReady = false;
    emit({ event: "windowClosed", params: {} });
  });
}

function avatarFileUrl(rawPath) {
  // The page cannot fetch file:// URLs; serve library files through the
  // privileged avatar:// scheme instead.
  return AVATAR_URL_PREFIX + encodeURIComponent(rawPath);
}

function avatarUrlToFilePath(url) {
  if (!url.startsWith(AVATAR_URL_PREFIX)) {
    throw new Error("unrecognized avatar url");
  }
  return decodeURIComponent(url.slice(AVATAR_URL_PREFIX.length));
}

async function handleCommand(request) {
  await app.whenReady();
  let params = request.params || {};
  switch (request.command) {
    case "ShowWindow":
      if (!window) createWindow(params);
      window.show();
      emit({ id: request.id, ok: true, result: { visible: true } });
      return;
    case "HideWindow":
      if (window && !window.isDestroyed()) window.hide();
      emit({ id: request.id, ok: true, result: { visible: false } });
      return;
    default:
      // Scene commands (LoadAvatar, SetExpression, ...) run in the page.
      if (request.command === "LoadAvatar" && params.path) {
        params = { ...params, path: avatarFileUrl(params.path) };
      }
      sendToPage(request);
      return;
  }
}

function main() {
  if (!process.versions.electron) {
    emit({
      event: "rendererError",
      params: {
        reason:
          "zara-avatar renderer must run under electron (npx electron main.mjs)",
      },
    });
    process.exit(2);
  }
  protocol.registerSchemesAsPrivileged([
    {
      scheme: AVATAR_SCHEME,
      privileges: { secure: true, supportFetchAPI: true, stream: true },
    },
  ]);

  createInterface({ input: process.stdin, crlfDelay: Infinity }).on(
    "line",
    (line) => {
      const text = line.trim();
      if (!text) return;
      let request;
      try {
        request = JSON.parse(text);
      } catch {
        return;
      }
      if (request.command === "Shutdown") {
        app.quit();
        return;
      }
      handleCommand(request).catch((error) => {
        if (request.id !== undefined) {
          emit({
            id: request.id,
            ok: false,
            error: String(error?.message || error),
          });
        }
      });
    },
  );
  // If the plugin dies without sending Shutdown, stdin EOF must terminate
  // the renderer so no orphan window survives.
  process.stdin.on("close", () => {
    app.quit();
  });

  ipcMain.handle("avatar-response", (_event, response) => {
    emit(response);
    return true;
  });
  ipcMain.on("page-ready", () => {
    pageReady = true;
    while (pendingToPage.length) {
      const document = pendingToPage.shift();
      window?.webContents?.send("avatar-command", document);
    }
    emit({ event: "windowReady", params: {} });
  });
  ipcMain.on("page-event", (_event, document) => {
    emit(document);
  });

  app.whenReady().then(() => {
    protocol.handle(AVATAR_SCHEME, (request) => {
      try {
        const filePath = avatarUrlToFilePath(request.url);
        return net.fetch(pathToFileURL(filePath).toString());
      } catch (error) {
        return new Response(String(error?.message || error), { status: 400 });
      }
    });
    // The page must exist before any scene command: a LoadAvatar sent to a
    // renderer without a window would otherwise queue until a window is
    // requested. The window stays hidden until ShowWindow.
    createWindow({});
    emit({ event: "ready", params: { renderer: "electron" } });
  });

  app.on("window-all-closed", () => {
    app.quit();
  });
}

main();
