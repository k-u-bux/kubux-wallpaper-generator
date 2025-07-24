{
  description = "Kubux Wallpaper Generator";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        
        pythonWithPackages = pkgs.python3.withPackages (ps: with ps; [
          tkinter
          pillow
          requests
          python-dotenv
          pip
        ]);
      in
      {
        packages.default = pkgs.stdenv.mkDerivation {
          pname = "kubux-wallpaper-generator";
          version = "1.0.0";
          
          src = ./.;
          
          nativeBuildInputs = [ pkgs.makeWrapper ];
          
          installPhase = ''
            mkdir -p $out/bin $out/share/applications $out/share/icons
            
            # Install the Python script
            cp kubux-wallpaper-generator.py $out/bin/kubux-wallpaper-generator.py
            
            # Install icon hierarchy if it exists
            if [ -d "hicolor" ]; then
              echo "Installing hicolor icon theme..."
              cp -r hicolor $out/share/icons/
            else
              echo "Warning: hicolor directory not found, icons may not display properly"
            fi

            # Create a shell wrapper that handles the together dependency           
            cat > $out/bin/kubux-wallpaper-generator << 'EOF'
            #!/usr/bin/env bash

            # Create a temporary directory for pip installs
            export TMPDIR=${TMPDIR:-/tmp}
            PIP_CACHE_DIR="$HOME/.cache/pip-kubux"
            mkdir -p "$PIP_CACHE_DIR"
            
            # Check if together is installed, install to a local directory if not
            PYTHONPATH_EXTRA="$HOME/.local/lib/python3.13/site-packages"
            mkdir -p "$PYTHONPATH_EXTRA"

            if ! PYTHONPATH="$PYTHONPATH_EXTRA:$PYTHONPATH" ${pythonEnv}/bin/python -c "import together" 2>/dev/null; then
                echo "Installing together package..."
                    ${pythonEnv}/bin/python -m pip install \
                            --target "$PYTHONPATH_EXTRA" \
                            --cache-dir "$PIP_CACHE_DIR" \
                            together
            fi

            # Run the application with the additional Python path
            # Use exec -a to set the process name for GNOME to recognize
            exec -a "kubux-wallpaper-generator" env PYTHONPATH="$PYTHONPATH_EXTRA:$PYTHONPATH" \
                ${pythonEnv}/bin/python "$out/bin/kubux-wallpaper-generator.py" "$@"
            EOF
            
            chmod +x $out/bin/kubux-wallpaper-generator
            
            # Install desktop file
            cp kubux-wallpaper-generator.desktop $out/share/applications/
            substitute kubux-wallpaper-generator.desktop \
              $out/share/applications/kubux-wallpaper-generator.desktop \
              --replace "Exec=kubux-wallpaper-generator" \
              "Exec=$out/bin/kubux-wallpaper-generator"
          '';
          
          # Add postInstall hook to update icon cache
          postInstall = ''
            # Update icon cache if gtk-update-icon-cache is available
            if command -v gtk-update-icon-cache >/dev/null 2>&1; then
              gtk-update-icon-cache $out/share/icons/hicolor || true
            fi
          '';
          
          meta = with pkgs.lib; {
            description = "AI-powered wallpaper generator using Together.ai";
            license = licenses.mit;
            platforms = platforms.all;
          };
        };

        apps.default = flake-utils.lib.mkApp {
          drv = self.packages.${system}.default;
          exePath = "/bin/kubux-wallpaper-generator";
        };

        devShells.default = pkgs.mkShell {
          buildInputs = [ pythonWithPackages ];
          shellHook = ''
            echo "Development environment for Kubux Wallpaper Generator"
            echo "You can run the script directly with: python kubux-wallpaper-generator.py"
          '';
        };
      });
}