{
  description = "Numerical checker contracts investigation";
  inputs = {
    base.url = "path:/home/onyr/nix-dev-base";
    nixpkgs.follows = "base/nixpkgs";
    flake-utils.follows = "base/flake-utils";
  };
  outputs = { base, nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let pkgs = import nixpkgs { inherit system; config.allowUnfree = true; };
      in {
        devShells.default = pkgs.mkShell {
          inputsFrom = [ base.devShells.${system}.default ];
          packages = [ ];
          shellHook = ''
            export NCCI_PYTHON_311="${pkgs.python311}/bin/python3.11"
            export NCCI_PYTHON_312="${pkgs.python312}/bin/python3.12"
            export NCCI_PYTHON_313="${pkgs.python313}/bin/python3.13"
            export NCCI_PYTHON_314="${pkgs.python314}/bin/python3.14"
            echo "[numerical-checker-contracts] investigation shell active"
          '';
        };
      });
}
