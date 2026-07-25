{
  description = "Kubux Wallpaper Generator v2 - AI-powered wallpaper creation tool (PySide6)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        
        togetherPkg = pkgs.python3Packages.buildPythonPackage rec {
          pname = "together";
          version = "1.5.35";
          format = "wheel";
          src = pkgs.fetchPypi {
            inherit pname version format;
            sha256 = "sha256-dLYZLiZJLbziVw+4AfiE50c5uuEEWyDFsHCnFjnX1fw=";
            dist = "py3";
            python = "py3";
          };
          propagatedBuildInputs = with pkgs.python3Packages; [
            requests pydantic typing-extensions aiohttp httpx anyio
            distro sniffio filelock rich tqdm
          ];
          doCheck = false;
          meta = with pkgs.lib; {
            description = "Python client for Together AI API";
            homepage = "https://pypi.org/project/together/";
            license = licenses.mit;
          };
        };
        
        pythonEnv = pkgs.python3.withPackages (ps: with ps; [
          pyside6 pillow requests watchdog python-dotenv togetherPkg
        ]);
        
      in
      {
        packages.default = pkgs.stdenv.mkDerivation {
          pname = "kubux-wallpaper-generator";
          version = "2.0.0";
          src = ./.;
          buildInputs = [ pythonEnv pkgs.imagemagick ];
          nativeBuildInputs = [ pkgs.makeWrapper ];
          installPhase = ''
            mkdir -p $out/bin
            mkdir -p $out/share/applications
            mkdir -p $out/share/man/man1
            cp kubux-wallpaper-generator.py $out/bin/kubux-wallpaper-generator.py
            chmod +x $out/bin/kubux-wallpaper-generator.py
            cp kubux-wallpaper-generator.1 $out/share/man/man1/kubux-wallpaper-generator.1
            makeWrapper ${pythonEnv}/bin/python $out/bin/kubux-wallpaper-generator \
              --add-flags "$out/bin/kubux-wallpaper-generator.py" \
              --set-default TMPDIR "/tmp"
            cp kubux-wallpaper-generator.desktop $out/share/applications/
            for size in 16x16 22x22 24x24 32x32 48x48 64x64 96x96 128x128 192x192 256x256; do
              mkdir -p $out/share/icons/hicolor/$size/apps
              magick convert app-icon.png -resize $size $out/share/icons/hicolor/$size/apps/kubux-wallpaper-generator.png
            done
          '';
          meta = with pkgs.lib; {
            description = "AI-powered wallpaper creation tool (PySide6)";
            homepage = "https://github.com/kubux/kubux-wallpaper-generator";
            license = licenses.asl20;
            maintainers = [ ];
            platforms = platforms.linux;
          };
        };
        
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            python3 pythonEnv imagemagick jetbrains.pycharm-community
            python3Packages.scancode-toolkit python3Packages.cython
            python3Packages.pip python3Packages.black python3Packages.flake8
          ];
          shellHook = ''
            export SCANCODE_CACHE=$HOME/.cache/scancode-cache
            export SCANCODE_LICENSE_INDEX_CACHE=$HOME/.cache/scancode-license-cache
            ln -s $( which python ) python
            echo "Kubux Wallpaper Generator v2 development environment"
            echo "Dependencies: PySide6, pillow, requests, watchdog, python-dotenv, together"
            echo "Run: python kubux-wallpaper-generator.py"
            cleanup() {
              [ -L ./python ] && rm ./python
              [ -L ./result ] && rm ./result
            }
            trap cleanup EXIT
          '';
        };
      });
}