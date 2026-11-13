# Run in models/. The .sh entry locates this directory for external callers.
groups = [("tank", ["tank_hull","tank_turret"]),
          ("infantry", ["infantry","infantry_kit","infantry_rifle"]),
          ("truck", ["truck","truck_kit","truck_canvas"]),
          ("hq", ["hq","hq_fence","hq_dish"])].
command argv = status = unwrap (Proc.streamNow (ProcessSpec argv "" [] "" 0));
  if status == 0 then Unit else error "exit {status}: {argv}".
part compiler dir name =
  path = "{dir}/{name}";
  _ = command [compiler,"{path}.coscad"];
  command ["xvfb-run","-a","openscad","-o","{path}.stl","-D","$fn=10","{path}.scad"].
render compiler (dir, names) = List.map (part compiler dir) names.
pack (dir, names) = inputs = List.map (fn name -> "{name}={dir}/{name}.stl") names;
  runner = (case unwrap (Env.get "SOL") of EnvText value -> value | EnvMissing -> "sol");
  command (List.append [runner,"../tools/mkmesh.sol","{dir}/{dir}.fpr"] inputs).
> compiler = (case unwrap (Env.get "COSCAD") of EnvText value -> if value == "" then "coscad" else value | EnvMissing -> "coscad");
  _ = List.map (render compiler) groups;
  _ = List.map pack groups; Unit.
