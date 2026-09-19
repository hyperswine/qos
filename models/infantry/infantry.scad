union() {
  union() {
    union() {
      union() {
        union() {
          union() {
            translate([-0.16, 0, 0]) {
              translate([0, -8.0e-2, 0]) {
                translate([0, 0, 0.12]) {
                  cube([0.14, 0.16, 0.38]);
                }
              }
            }
            translate([2.0e-2, 0, 0]) {
              translate([0, -8.0e-2, 0]) {
                translate([0, 0, 0.12]) {
                  cube([0.14, 0.16, 0.38]);
                }
              }
            }
          }
          translate([-0.21, 0, 0]) {
            translate([0, -0.12, 0]) {
              translate([0, 0, 0.5]) {
                cube([0.42, 0.24, 0.36]);
              }
            }
          }
        }
        translate([-0.25, 0, 0]) {
          translate([0, -0.11, 0]) {
            translate([0, 0, 0.78]) {
              cube([0.5, 0.22, 0.1]);
            }
          }
        }
      }
      translate([0, 0, 0.88]) {
        cylinder(h = 0.18, r = 0.11, $fn = 6);
      }
    }
    translate([0.21, 0, 0]) {
      translate([0, 0.0, 0]) {
        translate([0, 0, 0.62]) {
          cube([0.1, 0.26, 0.1]);
        }
      }
    }
  }
  translate([-0.31, 0, 0]) {
    translate([0, -2.0e-2, 0]) {
      translate([0, 0, 0.55]) {
        cube([0.1, 0.3, 0.1]);
      }
    }
  }
}
$fn = 50;