export interface FieldErrorProps {
  id: string;
  message: string | null;
}

/** Inline validation message for a single field. Renders nothing when
 * `message` is `null`, so callers can wire it in unconditionally. */
export function FieldError({ id, message }: FieldErrorProps) {
  if (!message) {
    return null;
  }
  return (
    <p id={id} role="alert" className="text-xs text-destructive">
      {message}
    </p>
  );
}
