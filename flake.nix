{
  description = "Kubux Wallpaper Generator - AI-powered wallpaper creation tool";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        
        # Define Python environment with all required packages
        pythonEnv = pkgs.python3.withPackages (ps: with ps; [
          tkinter
          pillow
          requests
          python-dotenv
        ]);
        
      in
      {
        packages.default = pkgs.stdenv.mkDerivation {
          pname = "kubux-wallpaper-generator";
          version = "1.0.0";
          
          src = ./.;
          
          buildInputs = [ pythonEnv ];
          nativeBuildInputs = [ pkgs.makeWrapper ];
          
          installPhase = ''
            mkdir -p $out/bin
            mkdir -p $out/share/applications
            mkdir -p $out/share/icons/hicolor/{16x16,22x22,24x24,32x32,48x48,64x64,128x128,256x256}/apps
            
            # Copy the Python script
            cp kubux-wallpaper-generator.py $out/bin/kubux-wallpaper-generator.py
            chmod +x $out/bin/kubux-wallpaper-generator.py
            
            # Create wrapper using makeWrapper
            makeWrapper ${pythonEnv}/bin/python $out/bin/kubux-wallpaper-generator \
              --add-flags "$out/bin/kubux-wallpaper-generator.py" \
              --set-default TMPDIR "/tmp" \
              --run 'mkdir -p "$HOME/.cache/pip-kubux"' \
              --run 'mkdir -p "$HOME/.local/lib/python3.13/site-packages"' \
              --run 'export PYTHONPATH_EXTRA="$HOME/.local/lib/python3.13/site-packages"' \
              --run 'if ! PYTHONPATH="$PYTHONPATH_EXTRA:$PYTHONPATH" ${pythonEnv}/bin/python -c "import together" 2>/dev/null; then echo "Installing together package..."; ${pythonEnv}/bin/python -m pip install --target "$PYTHONPATH_EXTRA" --cache-dir "$HOME/.cache/pip-kubux" together; fi' \
              --prefix PYTHONPATH : '$HOME/.local/lib/python3.13/site-packages'
            
            # Copy desktop file
            cp kubux-wallpaper-generator.desktop $out/share/applications/
            
            # Copy icons to all size directories
            for size in 16x16 22x22 24x24 32x32 48x48 64x64 128x128 256x256; do
              if [ -f hicolor/$size/apps/kubux-wallpaper-generator.png ]; then
                cp hicolor/$size/apps/kubux-wallpaper-generator.png $out/share/icons/hicolor/$size/apps/
              fi
            done
          '';
          
          meta = with pkgs.lib; {
            description = "AI-powered wallpaper creation tool";
            homepage = "https://github.com/yourusername/kubux-wallpaper-generator";
            license = licenses.mit;
            maintainers = [ ];
            platforms = platforms.linux;
          };
        };
        
        # Development shell
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            pythonEnv
            imagemagick
          ];
        };
      });
}