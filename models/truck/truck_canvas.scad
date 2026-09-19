union() {
  translate([0, 6.0e-2, 0]) {
    translate([0, 0, 0.7]) {
      rotate([90.0, 0, 0]) {
        cylinder(h = 1.24, r = 0.46, $fn = 10);
      }
    }
  }
  translate([-0.46, 0, 0]) {
    translate([0, -1.2, 0]) {
      translate([0, 0, 0.82]) {
        cube([0.92, 4.0e-2, 0.34]);
      }
    }
  }
}
$fn = 50;