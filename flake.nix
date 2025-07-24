{
  description = "Kubux Wallpaper Generator - AI-powered wallpaper creation tool";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python3.override {
          self = python;
          packageOverrides = pyfinal: pyprev: {
            together = pyfinal.callPackage ./dependencies/together {};
          };
        };
        name = "kubux-wallpaper-generator";
      in
      {
        devshell = pkgs.mkShell {
          packages = [
            (python.withPackages (python-pkgs: [
              # select Python packages here
              python-pkgs.together
              python-pkgs.tkinter
              python-pkgs.pillow
              python-pkgs.requests
              python-pkgs.python-dotenv
           ]))
          ];
        };
      }
    );
}