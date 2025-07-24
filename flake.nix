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
        
        # Define Python environment with basic packages
        pythonEnv = pkgs.python3.withPackages (ps: with ps; [
          tkinter
          pillow
          requests
        ]);
        
      in
      {
        packages.default = pkgs.stdenv.mkDerivation {
          pname = "kubux-wallpaper-generator";
          version = "1.0.0";
          
          src = ./.;
          
          buildInputs = [ pythonEnv ];
          
          installPhase = ''
            mkdir -p $out/bin
            mkdir -p $out/share/applications
            mkdir -p $out/share/icons/hicolor/{16x16,22x22,24x24,32x32,48x48,64x64,128x128,256x256,512x512}/apps
            
            # Copy the Python script
            cp kubux-wallpaper-generator.py $out/bin/kubux-wallpaper-generator.py
            chmod +x $out/bin/kubux-wallpaper-generator.py
            
            # Create the wrapper script
            cat > $out/bin/kubux-wallpaper-generator << 'WRAPPER_EOF'
            #!/usr/bin/env bash
            
            # Create a temporary directory for pip installs
            export TMPDIR=''${TMPDIR:-/tmp}
            PIP_CACHE_DIR="$HOME/.cache/pip-kubux"
            mkdir -p "$PIP_CACHE_DIR"
            
            # Check if together is installed, install to a local directory if not
            PYTHONPATH_EXTRA="$HOME/.local/lib/python3.13/site-packages"
            mkdir -p "$PYTHONPATH_EXTRA"
            
            if ! PYTHONPATH="$PYTHONPATH_EXTRA:$PYTHONPATH" PYTHON_BIN -c "import together" 2>/dev/null; then
                echo "Installing together package..."
                PYTHON_BIN -m pip install \
                    --target "$PYTHONPATH_EXTRA" \
                    --cache-dir "$PIP_CACHE_DIR" \
                    together
            fi
            
            # Run the application with the additional Python path
            exec env PYTHONPATH="$PYTHONPATH_EXTRA:$PYTHONPATH" \
                PYTHON_BIN "SCRIPT_PATH" "$@"
            WRAPPER_EOF
            
            # Replace placeholders in the wrapper
            sed -i "s|PYTHON_BIN|${pythonEnv}/bin/python|g" $out/bin/kubux-wallpaper-generator
            sed -i "s|SCRIPT_PATH|$out/bin/kubux-wallpaper-generator.py|g" $out/bin/kubux-wallpaper-generator
            
            chmod +x $out/bin/kubux-wallpaper-generator
            
            # Copy desktop file
            cp kubux-wallpaper-generator.desktop $out/share/applications/
            
            # Copy icons to all size directories
            for size in 16x16 22x22 24x24 32x32 48x48 64x64 128x128 256x256 512x512; do
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