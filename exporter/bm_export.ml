(* bm-export: a Catala 1.3.0 plugin that writes one scope of the typed default
   calculus (dcalc) as bm-ir v1 JSON. The format is specified in
   docs/bm-ir.md.

   The plugin is a mechanical serialisation. It does no arithmetic and no
   evaluation: every node it understands is written out as it stands, and any
   other node stops the export with "Unsupported construct <name> at
   <file>:<line>". The one structural change it makes is to inline the
   scopes called as sub-scopes, so that the result is a single flat list of
   definitions. *)

open Catala_utils
open Shared_ast

let bm_ir_version = 1

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

(* What a scope-level variable already declared stands for in the export:
   - [Name n]: an input or a definition, exported under the name [n];
   - [Subscope fields]: the result of a sub-scope call, whose output fields
     were exported under the names in [fields]. *)
type binding = Name of string | Subscope of string StructField.Map.t

(* Expressions. [bound] maps the scope-level variables already declared
   (inputs, earlier definitions and earlier sub-scope calls) to what they
   stand for; a reference to anything else is rejected, which also confirms
   the definitions are in dependency order. *)
let rec expr_json (bound : (expr, binding) Var.Map.t) (e : expr) : Yojson.Safe.t =
  let pos = Expr.pos e in
  let node k fields = `Assoc ((("k", `String k) :: fields) @ ["pos", pos_json pos]) in
  let var name = node "var" ["name", `String name] in
  let sub = expr_json bound in
  match Mark.remove e with
  | ELit l -> lit_json pos l
  | EVar v -> (
    match Var.Map.find_opt v bound with
    | Some (Name n) -> var n
    | Some (Subscope _) -> unsupported ("EVar " ^ Bindlib.name_of v ^ " (sub-scope result)") pos
    | None -> unsupported ("EVar " ^ Bindlib.name_of v) pos)
  (* [p.y], an output of the sub-scope [p], is a reference to the definition
     exported for it. *)
  | EStructAccess { e = EVar v, _; field; _ } -> (
    match Var.Map.find_opt v bound with
    | Some (Subscope fields) -> (
      match StructField.Map.find_opt field fields with
      | Some n -> var n
      | None -> unsupported "EStructAccess (not an output of the sub-scope)" pos)
    | _ -> unsupported "EStructAccess" pos)
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

(* Sub-scope calls. dcalc writes the definition of a sub-scope variable [p]
   declared with [p scope Sub] as

     let p : Sub =
       let result : Sub = Sub { Sub_in x_in = <argument>; ... } in
       let result1 : Sub = { Sub y = result.y; ... } in
       result1

   that is, in the AST,

     EApp { f = EAbs [result] (EApp { f = EAbs [result1] (EVar result1);
                                       args = [EStruct Sub { y = result.y }] });
            args = [EApp { f = EVar Sub; args = [EStruct Sub_in {...}] }] }

   where [Sub] is the variable that binds the called scope among the program's
   code items. [subscope_call] recognises exactly this shape and returns the
   called scope's variable and the fields of its input struct (the
   arguments). Anything else
   is left to [expr_json], which rejects an application. *)
let subscope_call (sl : expr scope_let) =
  match Mark.remove sl.scope_let_typ, Mark.remove sl.scope_let_expr with
  | ( TStruct out_struct,
      EApp
        {
          f = EAbs { binder = outer; _ }, _;
          args = [(EApp { f = EVar callee, _; args = [(EStruct { fields; _ }, _)]; _ }, _)];
          _;
        } ) -> (
    match Bindlib.unmbind outer with
    | [| result |], (EApp { f = EAbs { binder = inner; _ }, _; args = [copy]; _ }, _) -> (
      match Bindlib.unmbind inner, copy with
      | ([| result1 |], (EVar r1, _)), (EStruct { name = copy_struct; fields = copied }, _)
        when Var.equal r1 result1 && StructName.equal copy_struct out_struct
             && StructField.Map.for_all
                  (fun field (e : expr) ->
                    match Mark.remove e with
                    | EStructAccess { e = EVar r, _; field = f; name } ->
                      Var.equal r result && StructField.equal f field
                      && StructName.equal name out_struct
                    | _ -> false)
                  copied ->
        Some (callee, fields)
      | _ -> None)
    | _ -> None)
  | _ -> None

(* Scope body. dcalc gives the body as a chain of let-bindings over the input
   struct, in dependency order, ending with the output struct:
   - [DestructuringInputStruct]: [let x = Scope_in.x_in], one per input. For
     the top scope, the input becomes an entry in [inputs], and later
     references to it are plain variables, so the struct access is not
     written out. For a sub-scope, it becomes a definition whose expression is
     the caller's argument for that field.
   - [ScopeVarDefinition]: one per scope variable, internal or output. Each
     becomes an entry in [definitions], except a sub-scope call (see
     [subscope_call]), whose called scope is walked in its place.
   - The final expression is the output struct, whose fields name the
     outputs.

   [scopes] maps the variables that bind the scopes defined before this one to
   their bodies (see [find_scope]). A scope can only call a scope defined
   before it, so the inlining cannot recurse. [prefix] is the path of
   sub-scope names, ending in a dot, that names the variables of a sub-scope
   ("" for the top scope). [args] is the input struct of a sub-scope call, read
   in the caller's [caller_bound], and is [None] for the top scope.
   Definitions are accumulated in [defs]
   (most recent first) across every level, which keeps them in dependency
   order. The result is the scope's inputs, the definitions so far, and the
   output fields of the scope with the names they were exported under. *)
let rec scope_body_json ~scopes ~prefix ~args defs (body : expr scope_body) =
  let input_struct, lets = Bindlib.unbind body.scope_body_expr in
  let rec walk bound inputs defs (lets : expr scope_body_expr) =
    match lets with
    | Last result -> List.rev inputs, defs, outputs bound defs result
    | Cons (sl, next) -> (
      let v, rest = Bindlib.unbind next in
      let name = prefix ^ Bindlib.name_of v in
      let pos = sl.scope_let_pos in
      let definition expr =
        `Assoc
          [
            "name", `String name;
            "type", `String (definition_typ_name sl.scope_let_typ);
            "expr", expr;
          ]
      in
      match sl.scope_let_kind with
      | DestructuringInputStruct -> (
        let field =
          match Mark.remove sl.scope_let_expr with
          | EStructAccess { e = EVar s, _; field; _ } when Var.equal s input_struct -> field
          | _ -> unsupported "DestructuringInputStruct (not a plain input)" pos
        in
        (* An input must have a bm-ir type, in a sub-scope as in the top
           scope. This refuses a context input, which is a default term
           ([TDefault]). *)
        let ty = typ_name sl.scope_let_typ in
        let bound = Var.Map.add v (Name name) bound in
        match args with
        | None ->
          let input = `Assoc ["name", `String name; "type", `String ty] in
          walk bound (input :: inputs) defs rest
        | Some (caller_bound, fields) ->
          let arg =
            match StructField.Map.find_opt field fields with
            | Some arg -> arg
            | None -> unsupported ("sub-scope input " ^ name ^ " (no argument)") pos
          in
          walk bound inputs ((name, definition (expr_json caller_bound arg)) :: defs) rest)
      | ScopeVarDefinition -> (
        match subscope_call sl with
        | Some (callee, fields) ->
          let callee_body =
            match Var.Map.find_opt callee scopes with
            | Some body -> body
            | None -> unsupported "EApp (not a scope of this module)" pos
          in
          let _, defs, sub_outputs =
            scope_body_json ~scopes ~prefix:(name ^ ".") ~args:(Some (bound, fields)) defs
              callee_body
          in
          walk (Var.Map.add v (Subscope sub_outputs) bound) inputs defs rest
        | None ->
          let def = definition (expr_json bound sl.scope_let_expr) in
          walk (Var.Map.add v (Name name) bound) inputs ((name, def) :: defs) rest)
      | CallingSubScope -> unsupported "CallingSubScope" pos
      | DestructuringSubScopeResults -> unsupported "DestructuringSubScopeResults" pos
      | Assertion -> unsupported "Assertion" pos)
  and outputs bound defs (result : expr) =
    match Mark.remove result with
    | EStruct { fields; _ } ->
      (* Every output must be one of [definitions] (an input that is also an
         output is not supported). *)
      StructField.Map.map
        (fun (field : expr) ->
          match Mark.remove field with
          | EVar v -> (
            match Var.Map.find_opt v bound with
            | Some (Name n) when List.mem_assoc n defs -> n
            | Some (Name n) ->
              unsupported ("scope output " ^ n ^ " (not a definition)") (Expr.pos result)
            | _ -> unsupported "scope output (not a scope variable)" (Expr.pos field))
          | _ -> unsupported "scope output (not a scope variable)" (Expr.pos field))
        fields
    | _ -> unsupported "scope result (not a struct)" (Expr.pos result)
  in
  walk Var.Map.empty [] defs lets

let scope_json ~scopes ~scope_name (body : expr scope_body) =
  let inputs, defs, outputs = scope_body_json ~scopes ~prefix:"" ~args:None [] body
  in
  let defs = List.rev defs in
  (* Outputs follow the order of [definitions]. *)
  let output_names = StructField.Map.fold (fun _ n acc -> n :: acc) outputs [] in
  let outputs =
    List.filter_map
      (fun (n, _) -> if List.mem n output_names then Some (`String n) else None)
      defs
  in
  `Assoc
    [
      "bm_ir_version", `Int bm_ir_version;
      "catala_version", `String Cli.version;
      "scope", `String scope_name;
      "inputs", `List inputs;
      "outputs", `List outputs;
      "definitions", `List (List.map snd defs);
    ]

(* The program's code items are a chain of bindings, each scope bound to a
   variable that later scopes use to call it. They are walked once, so that
   the variables in the requested scope's body are the ones recorded here.
   The result maps each scope before the requested one to its body, and gives
   the requested scope's body. *)
let find_scope (code_items : expr code_item_list) scope_uid =
  let rec go scopes = function
    | Last _ -> raise Not_found
    | Cons (item, next) -> (
      let v, rest = Bindlib.unbind next in
      match item with
      | ScopeDef (name, body) when ScopeName.equal name scope_uid -> scopes, body
      | ScopeDef (_, body) -> go (Var.Map.add v body scopes) rest
      | Topdef _ -> go scopes rest)
  in
  go Var.Map.empty code_items

let run includes stdlib ex_scope output options =
  let prg, _ =
    Driver.Passes.dcalc options ~includes ~stdlib ~optimize:false
      ~check_invariants:false ~autotest:false ~typed:Expr.typed
  in
  let scope_uid = Driver.Commands.get_scope_uid prg.decl_ctx ex_scope in
  let scopes, body = find_scope prg.code_items scope_uid in
  let json =
    try scope_json ~scopes ~scope_name:ex_scope body
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
      "Writes one scope of the typed default calculus as bm-ir v1 JSON, the \
       format specified in docs/bm-ir.md of benefits-modeller-v2. Scopes \
       called as sub-scopes are inlined."
