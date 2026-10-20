//! Constant expressions: `localparam` / `parameter` values, enum labels, range bounds, `$past` depths. Integer
//! arithmetic in 64 bits (two's complement, as `longint`); names are looked up through `lookup`.

use crate::ast::{BinOp, Expr, UnOp};

/// The value of a constant expression, or why it has none.
pub fn eval(e: &Expr, lookup: &dyn Fn(&str) -> Option<Result<i64, String>>) -> Result<i64, String> {
    let ev = |x: &Expr| eval(x, lookup);
    Ok(match e {
        Expr::Number { value, unknown, text, .. } => {
            if *unknown != 0 {
                return Err(format!("{text} has x / z bits"));
            }
            *value as i64
        }
        Expr::Const { value, .. } => *value,
        Expr::Ident { name, .. } => match lookup(name) {
            Some(r) => r?,
            None => return Err(format!("'{name}' is not a constant")),
        },
        Expr::Fill { bit: '0', .. } => 0,
        Expr::Fill { bit, .. } => return Err(format!("'{bit} has no fixed width")),
        Expr::Unary { op, a, .. } => {
            let a = ev(a)?;
            match op {
                UnOp::Not => (a == 0) as i64,
                UnOp::BitNot => !a,
                UnOp::Neg => a.wrapping_neg(),
                UnOp::Plus => a,
                _ => return Err(format!("reduction {} needs a width", op.sym())),
            }
        }
        Expr::Binary { op, a, b, .. } => {
            let (a, b) = (ev(a)?, ev(b)?);
            use BinOp::*;
            match op {
                Pow => {
                    if b < 0 {
                        return Err("negative exponent".into());
                    }
                    a.wrapping_pow(b.min(u32::MAX as i64) as u32)
                }
                Mul => a.wrapping_mul(b),
                Div | Mod if b == 0 => return Err("division by zero".into()),
                Div => a.wrapping_div(b),
                Mod => a.wrapping_rem(b),
                Add => a.wrapping_add(b),
                Sub => a.wrapping_sub(b),
                Shl | AShl => a.checked_shl(b as u32).unwrap_or(0),
                Shr => (a as u64).checked_shr(b as u32).unwrap_or(0) as i64,
                AShr => a >> (b.clamp(0, 63)),
                Lt => (a < b) as i64,
                Le => (a <= b) as i64,
                Gt => (a > b) as i64,
                Ge => (a >= b) as i64,
                Eq | CaseEq => (a == b) as i64,
                Ne | CaseNe => (a != b) as i64,
                BitAnd => a & b,
                BitXor => a ^ b,
                BitXnor => !(a ^ b),
                BitOr => a | b,
                LogAnd => (a != 0 && b != 0) as i64,
                LogOr => (a != 0 || b != 0) as i64,
            }
        }
        Expr::Cond { c, a, b, .. } => {
            if ev(c)? != 0 {
                ev(a)?
            } else {
                ev(b)?
            }
        }
        Expr::Cast { width, a, .. } => {
            let v = ev(a)?;
            if *width >= 64 {
                v
            } else {
                (v as u64 & ((1u64 << width) - 1)) as i64   // 63'(x): 1 << 63 as i64 would overflow
            }
        }
        Expr::Call { func, args, .. } if func == "$clog2" => {
            let v = ev(&args[0])?;
            if v <= 1 {
                0
            } else {
                64 - ((v - 1) as u64).leading_zeros() as i64
            }
        }
        Expr::Call { func, .. } => return Err(format!("{func} is not constant")),
        Expr::Select { .. } | Expr::Concat { .. } | Expr::Repl { .. } | Expr::Inside { .. } => {
            return Err("selects, concatenations and inside are not evaluated in constants".into())
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::parse_expr;

    fn val(src: &str) -> Result<i64, String> {
        let e = parse_expr(src).unwrap();
        eval(&e, &|n| match n {
            "N" => Some(Ok(4)),
            "W" => Some(Ok(8)),
            "BAD" => Some(Err("no value".into())),
            _ => None,
        })
    }

    #[test]
    fn arithmetic() {
        assert_eq!(val("1 + 2 * 3"), Ok(7));
        assert_eq!(val("(1 + 2) * 3"), Ok(9));
        assert_eq!(val("2 ** 10 - 1"), Ok(1023));
        assert_eq!(val("N / 2 - 1"), Ok(1));
        assert_eq!(val("17 % 5"), Ok(2));
        assert_eq!(val("-N + 1"), Ok(-3));
        assert_eq!(val("1 << W"), Ok(256));
        assert_eq!(val("256 >> 4"), Ok(16));
        assert_eq!(val("-16 >>> 2"), Ok(-4));
        assert_eq!(val("8'hF0 | 4'h3"), Ok(0xF3));
        assert_eq!(val("6 & 3 ^ 1"), Ok(3)); // & before ^
        assert_eq!(val("~0"), Ok(-1));
    }

    #[test]
    fn logic_compare_conditional() {
        assert_eq!(val("N > 3 && W == 8"), Ok(1));
        assert_eq!(val("!N || 0"), Ok(0));
        assert_eq!(val("N >= 5 ? 10 : 20"), Ok(20));
        assert_eq!(val("N != 4"), Ok(0));
    }

    #[test]
    fn casts_and_clog2() {
        assert_eq!(val("2'(N / 2 - 1)"), Ok(1));
        assert_eq!(val("2'(7)"), Ok(3));
        assert_eq!(val("$clog2(1)"), Ok(0));
        assert_eq!(val("$clog2(8)"), Ok(3));
        assert_eq!(val("$clog2(9)"), Ok(4));
        assert_eq!(val("$clog2(W * 4)"), Ok(5));
    }

    #[test]
    fn not_constant() {
        assert_eq!(val("req + 1"), Err("'req' is not a constant".into()));
        assert_eq!(val("BAD"), Err("no value".into()));
        assert_eq!(val("1 / (N - 4)"), Err("division by zero".into()));
        assert_eq!(val("4'b1x00"), Err("4'b1x00 has x / z bits".into()));
        assert_eq!(val("&N"), Err("reduction & needs a width".into()));
        assert_eq!(val("$rose(N)"), Err("$rose is not constant".into()));
        assert_eq!(val("'1"), Err("'1 has no fixed width".into()));
        assert_eq!(val("'0"), Ok(0));
    }
    #[test]
    fn boundaries_do_not_overflow() {
        assert_eq!(val("63'(-1)"), Ok(i64::MAX));
        assert_eq!(val("63'(1)"), Ok(1));
        assert_eq!(val("64'(-1)"), Ok(-1));
        assert_eq!(val("9223372036854775807 + 1"), Ok(i64::MIN));   // 64-bit arithmetic wraps, as in SystemVerilog
        assert_eq!(val("1 << 64"), Ok(0));
    }
}
