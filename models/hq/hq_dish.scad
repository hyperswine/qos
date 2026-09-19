union() {
  union() {
    union() {
      translate([0, 0, 0.0]) {
        cylinder(h = 0.35, r = 9.0e-2, $fn = 8);
      }
      translate([0, 0, 0.4]) {
        rotate([-55.0, 0, 0]) {
          cylinder(h = 5.0e-2, r = 0.42, $fn = 10);
        }
      }
    }
    translate([0, 0, 0.4]) {
      rotate([-55.0, 0, 0]) {
        cylinder(h = 0.38, r = 2.5e-2, $fn = 6);
      }
    }
  }
  translate([0, 0, 0.4]) {
    rotate([-55.0, 0, 0]) {
      translate([0, 0, 0.36]) {
        cylinder(h = 6.0e-2, r = 6.0e-2, $fn = 6);
      }
    }
  }
}
$fn = 50;