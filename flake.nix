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

          # Match Zara's pinned runtime; plugin code is stdlib-only but the
          # test suites run against the same interpreter Zara uses. Declared
          # plugin dependencies are included in that plugin's installer and
          # test interpreter.
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

          developmentPython = python.withPackages (packages:
            map
              (dependency: packages.${dependency})
              (pkgs.lib.unique (
                pkgs.lib.concatMap
                  (entry: entry.python_dependencies or [ ])
                  plugins
              ))
          );

          # Install the plugin tree verbatim under share/zara/plugins/<name>
          # so layout-relative tooling (installer, renderer resolution) keeps
          # working from the store path, and expose the plugin CLI on bin/
          # when the plugin ships one.
          mkPluginPackage = entry:
            pkgs.stdenv.mkDerivation {
              pname = entry.name;
              inherit (entry) version;
              src = ./. + ("/plugins/" + entry.name);

              nativeBuildInputs = [ pkgs.makeWrapper ];

              installPhase = ''
                mkdir -p $out/share/zara/plugins
                cp -r $src $out/share/zara/plugins/${entry.name}
                chmod -R u+w $out/share/zara/plugins/${entry.name}
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
          } // pkgs.lib.listToAttrs (
            map
              (entry: pkgs.lib.nameValuePair "${entry.name}-tests" (
                pkgs.runCommand "zara-check-${entry.name}-tests"
                  {
                    nativeBuildInputs = [ (pythonFor entry) ];
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
