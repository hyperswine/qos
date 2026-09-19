union() {
  union() {
    union() {
      union() {
        union() {
          translate([-0.45, 0, 0]) {
            translate([0, -0.45, 0]) {
              translate([0, 0, 0.0]) {
                cube([0.9, 1.0, 0.36]);
              }
            }
          }
          translate([-0.35, 0, 0]) {
            translate([0, -0.35, 0]) {
              translate([0, 0, 0.36]) {
                cube([0.7, 0.8, 8.0e-2]);
              }
            }
          }
        }
        translate([-0.25, 0, 0]) {
          translate([0, 0.475, 0]) {
            translate([0, 0, 6.0e-2]) {
              cube([0.5, 0.25, 0.28]);
            }
          }
        }
      }
      translate([0, 0.6, 0]) {
        translate([0, 0, 0.2]) {
          rotate([-90.0, 0, 0]) {
            cylinder(h = 1.3, r = 7.0e-2, $fn = 8);
          }
        }
      }
    }
    translate([-9.0e-2, 0, 0]) {
      translate([0, 1.78, 0]) {
        translate([0, 0, 0.11]) {
          cube([0.18, 0.14, 0.18]);
        }
      }
    }
  }
  translate([-0.2, 0, 0]) {
    translate([0, -0.15, 0]) {
      translate([0, 0, 0.44]) {
        cylinder(h = 0.1, r = 0.14, $fn = 8);
      }
    }
  }
}
$fn = 50;