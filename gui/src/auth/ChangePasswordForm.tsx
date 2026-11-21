// Password change form, used at the first login (mandatory) and from the
// user menu. The checks done here (length, confirmation) only avoid a useless
// request: the controller checks again.
import { Alert, Button, PasswordInput, Stack, Text } from "@mantine/core";
import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { $api } from "../api/client";
import { errorKey } from "../api/errors";
import { refreshCurrentUser } from "./currentUser";

// minLength of new_password in PasswordChangeRequest (openapi/controller.json).
export const PASSWORD_MIN_LENGTH = 12;

type ChangePasswordFormProps = {
  /** Called once the controller accepted the new password. */
  onChanged?: () => void;
};

type Problem = "password.tooShort" | "password.mismatch" | null;

export function ChangePasswordForm({ onChanged }: ChangePasswordFormProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [problem, setProblem] = useState<Problem>(null);
  const change = $api.useMutation("post", "/api/v1/auth/password", {
    onSuccess: async () => {
      await refreshCurrentUser(queryClient);
      onChanged?.();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    let found: Problem = null;
    if (next.length < PASSWORD_MIN_LENGTH) {
      found = "password.tooShort";
    } else if (next !== confirmation) {
      found = "password.mismatch";
    }
    setProblem(found);
    if (found === null) {
      change.mutate({ body: { current_password: current, new_password: next } });
    }
  }

  return (
    <form onSubmit={submit}>
      <Stack>
        <PasswordInput
          label={t("password.current")}
          value={current}
          onChange={(event) => setCurrent(event.currentTarget.value)}
          autoComplete="current-password"
          required
          data-autofocus
        />
        <PasswordInput
          label={t("password.new")}
          description={t("password.hint", { min: PASSWORD_MIN_LENGTH })}
          value={next}
          onChange={(event) => setNext(event.currentTarget.value)}
          autoComplete="new-password"
          required
        />
        <PasswordInput
          label={t("password.confirm")}
          value={confirmation}
          onChange={(event) => setConfirmation(event.currentTarget.value)}
          autoComplete="new-password"
          required
        />
        {problem !== null && (
          <Alert color="red">{t(problem, { min: PASSWORD_MIN_LENGTH })}</Alert>
        )}
        {change.isError && <Alert color="red">{t(errorKey(change.error))}</Alert>}
        {change.isSuccess && <Text size="sm">{t("password.changed")}</Text>}
        <Button type="submit" loading={change.isPending}>
          {t("password.submit")}
        </Button>
      </Stack>
    </form>
  );
}
