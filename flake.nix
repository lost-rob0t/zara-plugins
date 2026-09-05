{
  description = "Public Zara plugin registry – discoverable, installable plugins for Zara";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs, ... }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" ];
      eachSystem = nixpkgs.lib.genAttrs supportedSystems;

      registry = builtins.fromJSON (builtins.readFile ./plugins.json);
      plugins = registry.plugins;

      mkSystem = system:
        let
          pkgs = import nixpkgs { inherit system; };

          # Match Zara's pinned runtime. Declared plugin dependencies are
          # included in the installer/test interpreter and in the immutable
          # runtime library exported by each plugin package.
          python = pkgs.python313;

          pythonFor = entry:
            let
              dependencies = entry.python_dependencies or [ ];
            in
            if dependencies == [ ] then
              python
            else
              python.withPackages (packages:
                map (dependency: packages.${dependency}) dependencies
              );

          testDependenciesFor = entry:
            map (dependency: pkgs.${dependency}) (entry.test_dependencies or [ ]);

          allPluginDependencies = pkgs.lib.unique (
            pkgs.lib.concatMap
              (entry: entry.python_dependencies or [ ])
              plugins
          );

          developmentPython = python.withPackages (packages:
            map (dependency: packages.${dependency}) allPluginDependencies
          );

          compatibilityPython = python.withPackages (packages:
            [ packages.langchain-core ]
            ++ map (dependency: packages.${dependency}) allPluginDependencies
          );

          installedCompatibilityPython = python.withPackages (packages: [
            packages.langchain-core
          ]);

          # Exact Zara source contract used by the generated compatibility
          # gate. Updating this revision is an explicit compatibility event.
          zaraSource = pkgs.fetchFromGitHub {
            owner = "lost-rob0t";
            repo = "zara";
            rev = "8e247fd4cb6ffe1f3258bfb4f115a3339208e8c1";
            hash = "sha256-c+qAYW1IKlhXknLzERFY2maa4GRY6gbGrsXMn9DSQrg=";
          };

          # Export a stable, immutable runtime layout for Home Manager and
          # other declarative consumers:
          #
          #   share/zara/runtime/<name>/entrypoint.py
          #   share/zara/runtime/<name>/lib/
          #
          # The lib directory combines plugin-owned Python modules with the
          # complete Python environment needed by declared dependencies. A
          # discovery entry can therefore prepend one directory and run
          # without an imperative installer copying dependencies into $HOME.
          runtimeLibraryFor = entry:
            let
              pluginSource = ./. + ("/plugins/" + entry.name);
              pluginPython = pythonFor entry;
            in
            pkgs.runCommand "${entry.name}-runtime-lib"
              { nativeBuildInputs = [ pkgs.coreutils ]; }
              ''
                mkdir -p "$out"

                if [ -d ${pluginSource}/lib ]; then
                  cp -r ${pluginSource}/lib/. "$out/"
                fi

                if [ -d ${pluginPython}/${python.sitePackages} ]; then
                  cp -rs ${pluginPython}/${python.sitePackages}/. "$out/"
                fi
              '';

          # Install the plugin tree verbatim under share/zara/plugins/<name>
          # so layout-relative tooling keeps working, and also publish the
          # declarative runtime layout above. Expose the plugin CLI on bin/
          # when the plugin ships one.
          mkPluginPackage = entry:
            let
              runtimeLibrary = runtimeLibraryFor entry;
            in
            pkgs.stdenv.mkDerivation {
              pname = entry.name;
              inherit (entry) version;
              src = ./. + ("/plugins/" + entry.name);

              nativeBuildInputs = [ pkgs.makeWrapper ];

              installPhase = ''
                mkdir -p $out/share/zara/plugins
                cp -r $src $out/share/zara/plugins/${entry.name}
                chmod -R u+w $out/share/zara/plugins/${entry.name}

                mkdir -p $out/share/zara/runtime/${entry.name}
                ln -s ${runtimeLibrary} $out/share/zara/runtime/${entry.name}/lib
                ln -s \
                  $out/share/zara/plugins/${entry.name}/${entry.entrypoint} \
                  $out/share/zara/runtime/${entry.name}/entrypoint.py
              '' + pkgs.lib.optionalString
                (builtins.pathExists (./. + "/plugins/${entry.name}/tools/${entry.name}")) ''
                mkdir -p $out/bin
                makeWrapper ${pythonFor entry}/bin/python3 $out/bin/${entry.name} \
                  --add-flags "$out/share/zara/plugins/${entry.name}/tools/${entry.name}"
              '';

              meta = {
                description = entry.description;
                license = pkgs.lib.licenses.gpl3Plus;
                platforms = supportedSystems;
              };
            };

          pluginPackages = pkgs.lib.listToAttrs (
            map (entry: pkgs.lib.nameValuePair entry.name (mkPluginPackage entry)) plugins
          );

          # One tree with every plugin under share/zara/plugins and every
          # plugin CLI on PATH; this is what downstream Zara flakes consume.
          pluginEnv = pkgs.symlinkJoin {
            name = "zara-plugins";
            version = registry.updated;
            paths = pkgs.lib.attrValues pluginPackages;
          };

          listApp = pkgs.writeShellScriptBin "zara-plugins-list" ''
            exec ${python}/bin/python3 - ${builtins.toFile "plugins.json" (builtins.toJSON registry)} <<'EOF'
            import json
            import sys

            registry = json.load(open(sys.argv[1]))
            print(f"Zara plugin registry (schema {registry['schema_version']}, updated {registry['updated']})")
            for plugin in registry["plugins"]:
                print(f"  {plugin['name']} {plugin['version']} [{plugin['plugin_type']}] {plugin['description']}")
                print(f"    install: {plugin.get('install', {}).get('tool', 'see plugin README')}")
            EOF
          '';

          checks = {
            registry = pkgs.runCommand "zara-check-registry"
              {
                nativeBuildInputs = [ python ];
                src = self;
              }
              ''
                ${python}/bin/python3 $src/scripts/validate-registry.py
                touch $out
              '';

            compatibility = pkgs.runCommand "zara-check-plugin-compatibility"
              {
                nativeBuildInputs = [ compatibilityPython ];
                src = self;
              }
              ''
                export HOME=$(mktemp -d)
                export XDG_CONFIG_HOME="$HOME/.config"
                ${compatibilityPython}/bin/python3 \
                  $src/scripts/zara_compat.py \
                  --root $src \
                  --zara-source ${zaraSource}
                touch $out
              '';

            installed-compatibility = pkgs.runCommand "zara-check-installed-plugin-compatibility"
              {
                nativeBuildInputs = [ installedCompatibilityPython ];
                src = self;
              }
              ''
                export HOME=$(mktemp -d)
                ${installedCompatibilityPython}/bin/python3 \
                  $src/scripts/zara_compat.py \
                  --root $src \
                  --runtime-root ${pluginEnv}/share/zara/runtime \
                  --zara-source ${zaraSource}
                touch $out
              '';

            runtime-layout = pkgs.runCommand "zara-check-runtime-layout"
              { nativeBuildInputs = [ python ]; }
              (pkgs.lib.concatMapStringsSep "\n"
                (entry: ''
                  test -f ${pluginPackages.${entry.name}}/share/zara/runtime/${entry.name}/entrypoint.py
                  test -d ${pluginPackages.${entry.name}}/share/zara/runtime/${entry.name}/lib
                '')
                plugins
              + ''
                PYTHONPATH=${pluginPackages.zara-discord}/share/zara/runtime/zara-discord/lib \
                  ${python}/bin/python3 -c 'import discord, audioop, zara_discord_service'
                touch $out
              '');
          } // pkgs.lib.listToAttrs (
            map
              (entry: pkgs.lib.nameValuePair "${entry.name}-tests" (
                pkgs.runCommand "zara-check-${entry.name}-tests"
                  {
                    nativeBuildInputs = [ (pythonFor entry) ] ++ testDependenciesFor entry;
                    src = self;
                  }
                  ''
                    export HOME=$(mktemp -d)
                    cp -r $src ./tree
                    chmod -R u+w ./tree
                    cd ./tree/plugins/${entry.name}
                    ${(pythonFor entry)}/bin/python3 -m unittest discover -s test -t test
                    touch $out
                  ''
              ))
              (
                builtins.filter
                  (entry: builtins.pathExists (./. + "/plugins/${entry.name}/test"))
                  plugins
              )
          );
        in
        {
          packages = pluginPackages // {
            zara-plugins = pluginEnv;
            default = pluginEnv;
          };

          apps = { } // pkgs.lib.listToAttrs (
            map
              (entry: pkgs.lib.nameValuePair entry.name {
                type = "app";
                program = "${pluginPackages.${entry.name}}/bin/${entry.name}";
              })
              (
                builtins.filter
                  (entry: builtins.pathExists (./. + "/plugins/${entry.name}/tools/${entry.name}"))
                  plugins
              )
          ) // {
            list = {
              type = "app";
              program = "${listApp}/bin/zara-plugins-list";
            };
            default = {
              type = "app";
              program = "${listApp}/bin/zara-plugins-list";
            };
          };

          checks = checks;

          devShells.default = pkgs.mkShell {
            name = "zara-plugins-dev-shell";

            packages = [
              developmentPython
              developmentPython.pkgs.pytest
              pkgs.nodejs
            ];

            shellHook = ''
              echo "Zara plugin registry dev shell (Python + pytest + node for renderer work)"
              echo ""
              echo "Commands:"
              echo "  python3 scripts/validate-registry.py                          # validate registry"
              echo "  python3 -m unittest discover -s plugins/<name>/test -t plugins/<name>/test"
              echo "  nix flake check                                               # registry + plugin suites"
            '';
          };
        };
    in
    {
      packages = nixpkgs.lib.mapAttrs (_: v: v.packages) (eachSystem mkSystem);
      apps = nixpkgs.lib.mapAttrs (_: v: v.apps) (eachSystem mkSystem);
      checks = nixpkgs.lib.mapAttrs (_: v: v.checks) (eachSystem mkSystem);
      devShells = nixpkgs.lib.mapAttrs (_: v: v.devShells) (eachSystem mkSystem);
    };
}
