# Scope Summary: Command Line Calculator

## Summary
The team is building a command-line calculator that performs basic arithmetic operations (addition, subtraction, multiplication, division) on two numbers at a time. The calculator runs in a continuous session, accepting user input in the format `<number> <operator> <number>`, displaying results, and prompting for additional calculations until the user exits with a quit command.

## Agreed Requirements

### Core Functionality
- **Operations supported**: Addition (+), subtraction (-), multiplication (*), division (/)
- **Operation scope**: Binary operations only (two numbers, one operator)
- **Input format**: `<number> <operator> <number>` with spaces required around the operator
- **Number support**: Floating-point numbers and negative numbers (validated by implementation language's standard float parser)
- **Session behavior**: Continuous loop with "> " prompt until user types "quit" or "exit"
- **Exit commands**: "quit" or "exit" (case-insensitive)
- **Output format**: Display full equation with result (e.g., `5 + 3 = 8`)
- **Startup message**: "Calculator ready. Type 'quit' to exit."

### Error Handling
- **Division by zero**: Display "Error: Division by zero" and return to prompt
- **Invalid input format**: Display "Error: Invalid format. Use: number operator number (with spaces)" and return to prompt
- **Invalid operator**: Display "Error: Invalid operator. Use +, -, *, or /" and return to prompt
- **Invalid number format**: Display "Error: Invalid number format" and return to prompt
- **Error behavior**: All errors return to prompt; program only exits on explicit quit command

### Edge Cases
- **Empty input**: Silent re-prompt (no error message)
- **Whitespace-only input**: Treated same as empty input
- **Multiple spaces between tokens**: Handled correctly (e.g., "5    +    3")
- **Leading/trailing whitespace**: Trimmed before processing
- **Very large numbers**: No artificial limits; rely on language capabilities
- **Number formats**: Accept standard decimal formats (5, 5.5, -5, 0.5) per language parser

### Acceptance Criteria Examples
- Basic operations: `5 + 3 = 8`, `10 - 4 = 6`, `3 * 4 = 12`, `10 / 2 = 5`
- Negative numbers: `-5 + 3 = -2`, `5 + -3 = 2`, `-5 - -3 = -2`
- Decimals: `5.5 + 2.3 = 7.8`, `10.5 / 2 = 5.25`
- All error conditions display appropriate messages and return to prompt
- Multiple calculations work in continuous session
- Case-insensitive exit commands function correctly

## Open Questions
None remaining. All initial questions were resolved during the grooming session.

## Assumptions
- The implementation language's standard float parser adequately handles number validation
- Standard system behavior for unexpected termination (e.g., crashes) is acceptable
- Users can adapt to the required-spaces input format without significant friction
- A one-line startup message provides sufficient user guidance

## Out of Scope
- **Chained operations**: Multiple operators/numbers in one expression (e.g., "5 + 3 + 2")
- **Operator precedence**: Handling expressions like "5 + 3 * 2"
- **Parentheses**: Grouping or nested expressions
- **Scientific notation**: Explicit support for formats like "5e10"
- **Operation history**: Storing or referencing previous calculations
- **Variables**: Named storage or "ans" functionality
- **Signal handling**: Specific behavior for Ctrl+C or other system signals (default system behavior acceptable)
- **Advanced number formats**: Specific validation rules beyond language parser capabilities
