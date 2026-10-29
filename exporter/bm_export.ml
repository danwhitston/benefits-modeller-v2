(* bm-export: a Catala 1.3.0 plugin that writes one scope of the typed default
   calculus (dcalc) as bm-ir v0 JSON. The format is specified in
   docs/bm-ir.md.

   The plugin is a mechanical serialisation. It does no arithmetic and no
   evaluation: every node it understands is written out as it stands, and any
   other node stops the export with "Unsupported construct <name> at
   <file>:<line>". *)

open Catala_utils
open Shared_ast

let bm_ir_version = 0

type expr = typed Dcalc.Ast.expr

exception Unsupported of string * Pos.t

let unsupported name pos = raise (Unsupported (name, pos))

(* Positions *)

(* Catala reports files as they were named on the command line. An absolute
   path under the working directory is made relative to it, and a leading
   "./" is dropped, so that running from the repository root gives paths
   relative to the root. *)
let relative_file file =
  let drop_prefix prefix s =
    if String.starts_with ~prefix s then
      Some (String.sub s (String.length prefix) (String.length s - String.length prefix))
    else None
  in
  let file =
    Option.value ~default:file (drop_prefix (Sys.getcwd () ^ Filename.dir_sep) file)
  in
  let rec drop_dot s = match drop_prefix "./" s with Some s -> drop_dot s | None -> s in
  drop_dot file

let pos_json pos =
  `Assoc
    [
      "file", `String (relative_file (Pos.get_file pos));
      "line", `Int (Pos.get_start_line pos);
    ]

(* Types *)

let typ_name (ty : typ) =
  let pos = Mark.get ty in
  match Mark.remove ty with
  | TLit TMoney -> "money"
  | TLit TRat -> "decimal"
  | TLit TInt -> "integer"
  | TLit TBool -> "bool"
  | TLit TDate -> "date"
  | TLit TUnit -> unsupported "TLit TUnit" pos
  | TLit TDuration -> unsupported "TLit TDuration" pos
  | TLit TPos -> unsupported "TLit TPos" pos
  | TError -> unsupported "TError" pos
  | TArrow _ -> unsupported "TArrow" pos
  | TTuple _ -> unsupported "TTuple" pos
  | TStruct _ -> unsupported "TStruct" pos
  | TEnum _ -> unsupported "TEnum" pos
  | TAbstract _ -> unsupported "TAbstract" pos
  | TOption _ -> unsupported "TOption" pos
  | TArray _ -> unsupported "TArray" pos
  | TDefault _ -> unsupported "TDefault" pos
  | TVar _ -> unsupported "TVar" pos
  | TForAll _ -> unsupported "TForAll" pos
  | TClosureEnv -> unsupported "TClosureEnv" pos

(* A scope variable that dcalc leaves as a default term (an internal variable
   whose uses are wrapped in error_on_empty) has type [TDefault t]. Its
   definition is written with type [t]; the default structure stays visible in
   the expression itself. *)
let definition_typ_name (ty : typ) =
  match Mark.remove ty with TDefault t -> typ_name t | _ -> typ_name ty

(* Literals: money as an integer number of pence, decimals as an exact
   numerator/denominator in lowest terms (zarith keeps [Q.t] normalised). *)
let lit_json pos (l : lit) =
  let ty, value =
    match l with
    | LBool b -> "bool", string_of_bool b
    | LInt i -> "integer", Z.to_string i
    | LRat q -> "decimal", Z.to_string (Q.num q) ^ "/" ^ Z.to_string (Q.den q)
    | LMoney m -> "money", Z.to_string m
    | LDate d ->
      let y, m, d = Catala_runtime.date_to_years_months_days d in
      "date", Printf.sprintf "%04d-%02d-%02d" y m d
    | LUnit -> unsupported "LUnit" pos
    | LDuration _ -> unsupported "LDuration" pos
  in
  `Assoc
    ["k", `String "lit"; "type", `String ty; "value", `String value; "pos", pos_json pos]

(* Operators, written under their Catala 1.3.0 constructor names. Only those
   whose operands and result are all bm-ir types are accepted. Comparisons are
   polymorphic in Catala 1.3.0 (there is no [Lt_mon_mon]), so their operand
   type comes from the operands. *)
let op_name pos (op : dcalc Op.t) =
  match op with
  | Not -> "Not"
  | And -> "And"
  | Or -> "Or"
  | Xor -> "Xor"
  | Eq -> "Eq"
  | Lt -> "Lt"
  | Lte -> "Lte"
  | Gt -> "Gt"
  | Gte -> "Gte"
  | Minus_int -> "Minus_int"
  | Minus_rat -> "Minus_rat"
  | Minus_mon -> "Minus_mon"
  | ToInt_rat -> "ToInt_rat"
  | ToInt_mon -> "ToInt_mon"
  | ToRat_int -> "ToRat_int"
  | ToRat_mon -> "ToRat_mon"
  | ToMoney_rat -> "ToMoney_rat"
  | ToMoney_int -> "ToMoney_int"
  | Round_rat -> "Round_rat"
  | Round_mon -> "Round_mon"
  | Add_int_int -> "Add_int_int"
  | Add_rat_rat -> "Add_rat_rat"
  | Add_mon_mon -> "Add_mon_mon"
  | Sub_int_int -> "Sub_int_int"
  | Sub_rat_rat -> "Sub_rat_rat"
  | Sub_mon_mon -> "Sub_mon_mon"
  | Mult_int_int -> "Mult_int_int"
  | Mult_rat_rat -> "Mult_rat_rat"
  | Mult_mon_int -> "Mult_mon_int"
  | Mult_mon_rat -> "Mult_mon_rat"
  | Div_int_int -> "Div_int_int"
  | Div_rat_rat -> "Div_rat_rat"
  | Div_mon_int -> "Div_mon_int"
  | Div_mon_rat -> "Div_mon_rat"
  | Div_mon_mon -> "Div_mon_mon"
  | op -> unsupported ("operator " ^ Operator.name op) pos

(* Expressions. [bound] holds the scope-level variables already declared
   (inputs and earlier definitions); a reference to anything else is
   rejected, which also confirms the definitions are in dependency order. *)
let rec expr_json (bound : expr Var.Set.t) (e : expr) : Yojson.Safe.t =
  let pos = Expr.pos e in
  let node k fields = `Assoc ((("k", `String k) :: fields) @ ["pos", pos_json pos]) in
  let sub = expr_json bound in
  match Mark.remove e with
  | ELit l -> lit_json pos l
  | EVar v ->
    if Var.Set.mem v bound then node "var" ["name", `String (Bindlib.name_of v)]
    else unsupported ("EVar " ^ Bindlib.name_of v) pos
  | EAppOp { op = op, op_pos; args; _ } ->
    node "op" ["op", `String (op_name op_pos op); "args", `List (List.map sub args)]
  | EIfThenElse { cond; etrue; efalse } ->
    node "if" ["cond", sub cond; "then", sub etrue; "else", sub efalse]
  | EDefault { excepts; just; cons } ->
    node "default"
      ["exceptions", `List (List.map sub excepts); "just", sub just; "cons", sub cons]
  | EPureDefault arg -> node "pure" ["arg", sub arg]
  | EEmpty -> node "empty" []
  | EErrorOnEmpty arg -> node "error_on_empty" ["arg", sub arg]
  | ELocation _ -> .
  | EApp _ -> unsupported "EApp" pos
  | EArray _ -> unsupported "EArray" pos
  | EAbs _ -> unsupported "EAbs" pos
  | EStruct _ -> unsupported "EStruct" pos
  | EInj _ -> unsupported "EInj" pos
  | EMatch _ -> unsupported "EMatch" pos
  | ETuple _ -> unsupported "ETuple" pos
  | ETupleAccess _ -> unsupported "ETupleAccess" pos
  | EAssert _ -> unsupported "EAssert" pos
  | EStructAccess _ -> unsupported "EStructAccess" pos
  | EExternal _ -> unsupported "EExternal" pos
  | EFatalError _ -> unsupported "EFatalError" pos
  | EPos _ -> unsupported "EPos" pos
  | EBad -> unsupported "EBad" pos

(* Scope body. dcalc gives the body as a chain of let-bindings over the input
   struct, in dependency order, ending with the output struct:
   - [DestructuringInputStruct]: [let x = Scope_in.x_in], one per input. The
     input becomes an entry in [inputs], and later references to it are plain
     variables, so the struct access is not written out.
   - [ScopeVarDefinition]: one per scope variable, internal or output. Each
     becomes an entry in [definitions].
   - The final expression is the output struct, whose fields name the
     outputs. *)
let scope_json ~scope_name (body : expr scope_body) =
  let input_struct, lets = Bindlib.unbind body.scope_body_expr in
  let rec walk bound inputs defs (lets : expr scope_body_expr) =
    match lets with
    | Last result -> List.rev inputs, List.rev defs, outputs bound defs result
    | Cons (sl, next) -> (
      let v, rest = Bindlib.unbind next in
      let name = Bindlib.name_of v in
      let pos = sl.scope_let_pos in
      match sl.scope_let_kind with
      | DestructuringInputStruct ->
        (match Mark.remove sl.scope_let_expr with
        | EStructAccess { e = EVar s, _; _ } when Var.equal s input_struct -> ()
        | _ -> unsupported "DestructuringInputStruct (not a plain input)" pos);
        let input =
          `Assoc ["name", `String name; "type", `String (typ_name sl.scope_let_typ)]
        in
        walk (Var.Set.add v bound) (input :: inputs) defs rest
      | ScopeVarDefinition ->
        let expr = expr_json bound sl.scope_let_expr in
        let def =
          `Assoc
            [
              "name", `String name;
              "type", `String (definition_typ_name sl.scope_let_typ);
              "expr", expr;
            ]
        in
        walk (Var.Set.add v bound) inputs ((name, def) :: defs) rest
      | CallingSubScope -> unsupported "CallingSubScope" pos
      | DestructuringSubScopeResults -> unsupported "DestructuringSubScopeResults" pos
      | Assertion -> unsupported "Assertion" pos)
  and outputs bound defs (result : expr) =
    match Mark.remove result with
    | EStruct { fields; _ } ->
      let names =
        StructField.Map.fold
          (fun _ (field : expr) acc ->
            match Mark.remove field with
            | EVar v when Var.Set.mem v bound -> Bindlib.name_of v :: acc
            | _ -> unsupported "scope output (not a scope variable)" (Expr.pos field))
          fields []
      in
      (* Every output must be one of [definitions] (an input that is also an
         output is not supported). Outputs follow the order of
         [definitions]. *)
      List.iter
        (fun n ->
          if not (List.mem_assoc n defs) then
            unsupported ("scope output " ^ n ^ " (not a definition)") (Expr.pos result))
        names;
      List.rev defs
      |> List.filter_map (fun (n, _) -> if List.mem n names then Some (`String n) else None)
    | _ -> unsupported "scope result (not a struct)" (Expr.pos result)
  in
  let inputs, defs, outputs = walk Var.Set.empty [] [] lets in
  `Assoc
    [
      "bm_ir_version", `Int bm_ir_version;
      "catala_version", `String Cli.version;
      "scope", `String scope_name;
      "inputs", `List inputs;
      "outputs", `List outputs;
      "definitions", `List (List.map snd defs);
    ]

let run includes stdlib ex_scope output options =
  let prg, _ =
    Driver.Passes.dcalc options ~includes ~stdlib ~optimize:false
      ~check_invariants:false ~autotest:false ~typed:Expr.typed
  in
  let scope_uid = Driver.Commands.get_scope_uid prg.decl_ctx ex_scope in
  let body =
    BoundList.find prg.code_items ~f:(function
      | ScopeDef (name, body) when ScopeName.equal name scope_uid -> Some body
      | _ -> None)
  in
  let json =
    try scope_json ~scope_name:ex_scope body
    with Unsupported (name, pos) ->
      Message.error ~pos "Unsupported construct %s at %s:%d" name
        (relative_file (Pos.get_file pos))
        (Pos.get_start_line pos)
  in
  let _, with_output = Driver.Commands.get_output options output in
  with_output (fun oc ->
      Yojson.Safe.pretty_to_channel oc json;
      output_char oc '\n')

let term =
  let open Cmdliner in
  Term.(
    const run
    $ Cli.Flags.include_dirs
    $ Cli.Flags.stdlib_dir
    $ Cli.Flags.ex_scope
    $ Cli.Flags.output)

let () =
  Driver.Plugin.register "bm-export" term
    ~doc:
      "Writes one scope of the typed default calculus as bm-ir v0 JSON, the \
       format specified in docs/bm-ir.md of benefits-modeller-v2."
