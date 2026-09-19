union() {
  union() {
    union() {
      union() {
        translate([-0.17, 0, 0]) {
          translate([0, -0.12, 0]) {
            translate([0, 0, 0.0]) {
              cube([0.16, 0.26, 0.12]);
            }
          }
        }
        translate([1.0e-2, 0, 0]) {
          translate([0, -0.12, 0]) {
            translate([0, 0, 0.0]) {
              cube([0.16, 0.26, 0.12]);
            }
          }
        }
      }
      translate([0, 0, 1.02]) {
        cylinder(h = 0.1, r = 0.14, $fn = 6);
      }
    }
    translate([0, 0, 1.0]) {
      cylinder(h = 3.0e-2, r = 0.17, $fn = 6);
    }
  }
  translate([-0.15, 0, 0]) {
    translate([0, -0.3, 0]) {
      translate([0, 0, 0.52]) {
        cube([0.3, 0.16, 0.3]);
      }
    }
  }
}
$fn = 50;