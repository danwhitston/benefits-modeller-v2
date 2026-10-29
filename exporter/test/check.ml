(* Test helper for the golden fixtures.

   check json EXPECTED ACTUAL
     Fails unless the two files hold equal JSON values. Layout does not
     matter, so the expected files can be written by hand.

   check contains EXPECTED ACTUAL
     Fails unless every line of EXPECTED appears as a substring of ACTUAL. *)

let read_file path = In_channel.with_open_bin path In_channel.input_all

let fail fmt = Printf.ksprintf (fun s -> prerr_endline s; exit 1) fmt

let check_json expected actual =
  let parse path =
    try Yojson.Safe.from_file path
    with Yojson.Json_error msg -> fail "%s: not valid JSON: %s" path msg
  in
  let e = parse expected and a = parse actual in
  if not (Yojson.Safe.equal (Yojson.Safe.sort e) (Yojson.Safe.sort a)) then
    fail "JSON mismatch.\n--- expected (%s)\n%s\n--- actual (%s)\n%s" expected
      (Yojson.Safe.pretty_to_string e)
      actual
      (Yojson.Safe.pretty_to_string a)

let contains ~sub s =
  let n = String.length sub and m = String.length s in
  let rec go i = i + n <= m && (String.sub s i n = sub || go (i + 1)) in
  go 0

let check_contains expected actual =
  let output = read_file actual in
  read_file expected |> String.split_on_char '\n'
  |> List.filter (fun l -> String.trim l <> "")
  |> List.iter (fun line ->
         if not (contains ~sub:line output) then
           fail "Expected %S in the output of %s, which was:\n%s" line actual
             output)

let () =
  match Sys.argv with
  | [| _; "json"; e; a |] -> check_json e a
  | [| _; "contains"; e; a |] -> check_contains e a
  | _ -> fail "usage: check (json|contains) EXPECTED ACTUAL"
