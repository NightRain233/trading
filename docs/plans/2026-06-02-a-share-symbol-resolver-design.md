# A-Share Symbol Resolver Design

## Goal

Allow users to type familiar A-share numeric codes in the watchlist add box, see clear candidate symbols with Chinese-market display codes and Yahoo symbols, then add the selected Yahoo-compatible symbol.

## Decisions

- Keep Yahoo-compatible symbols as the persisted watchlist format.
- Show A-share display codes as `.SH` and `.SZ` in the UI, while saving `.SS` and `.SZ` for Yahoo Finance.
- Treat `000001` as a special conflict where `000001.SS` (上证指数) is the first candidate, followed by `000001.SZ` (平安银行).
- Resolve `.SH` input to `.SS` on the backend.
- Leave non-A-share symbols such as `AAPL`, `BTC-USD`, and `GC=F` on the existing path.

## Architecture

The backend owns symbol normalization and candidate generation so every caller uses one rule set. A new `/api/symbol/resolve` endpoint accepts raw input and returns ordered candidates with `symbol`, `displayCode`, `name`, `market`, and `confidence`.

The frontend add-symbol form calls the resolver while the user types. It renders a compact dropdown for both unique and conflicting numeric inputs. Selecting an option fills the input with the Yahoo symbol; submitting without a selected candidate still goes through backend normalization.

## Candidate Strategy

Rules provide fast first-pass candidates:

- Shanghai: `600`, `601`, `603`, `605`, `688`, `510`, `511`, `512`, `513`, `515`, `516`, `517`, `518`, `588`.
- Shenzhen: `000`, `001`, `002`, `003`, `300`, `301`, `159`.
- Special conflict: `000001` returns `000001.SS` first, then `000001.SZ`.

Names come from a small built-in map for important ambiguous/common symbols first. If a symbol is not known locally, the UI still displays the full code and market so the user can choose safely; Yahoo lookup can be added later as a cache-backed enhancement.

## Error Handling

Empty queries return an empty candidate list. Unknown six-digit codes return likely candidates from rules when possible. Invalid or unsupported input returns an empty list from the resolver, while manual add still uses the existing watchlist failure path.

## Testing

Backend unit tests cover numeric inference, `.SH` conversion, the `000001` conflict order, and watchlist add normalization. Frontend verification uses TypeScript build and an in-browser smoke check of the dropdown.
