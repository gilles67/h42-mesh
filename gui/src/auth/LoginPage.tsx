// Login in two steps: username and password, then the TOTP code. The
// controller says which step comes next (LoginResponse.next_step); at the
// first login there is no TOTP yet, and the AuthGate shows the setup screens.
import { Alert, Button, PasswordInput, Stack, Text, TextInput } from "@mantine/core";
import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { $api } from "../api/client";
import { errorKey } from "../api/errors";
import { AuthLayout } from "./AuthLayout";
import { CODE_PATTERN, CodeInput } from "./CodeInput";
import { refreshCurrentUser } from "./currentUser";

type LoginPageProps = {
  /** The previous session has just expired: say so. */
  expired: boolean;
  /** Called when the controller accepted the login. */
  onLoggedIn: () => void;
};

export function LoginPage({ expired, onLoggedIn }: LoginPageProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [step, setStep] = useState<"password" | "totp">("password");

  function loggedIn() {
    onLoggedIn();
    void refreshCurrentUser(queryClient); // the AuthGate then shows what comes next
  }

  return (
    <AuthLayout title={t(step === "password" ? "login.title" : "login.totpTitle")}>
      {step === "password" ? (
        <>
          {expired && <Alert color="yellow">{t("login.expired")}</Alert>}
          <PasswordStep onTotp={() => setStep("totp")} onLoggedIn={loggedIn} />
        </>
      ) : (
        <TotpStep onBack={() => setStep("password")} onLoggedIn={loggedIn} />
      )}
    </AuthLayout>
  );
}

type PasswordStepProps = {
  onTotp: () => void;
  onLoggedIn: () => void;
};

function PasswordStep({ onTotp, onLoggedIn }: PasswordStepProps) {
  const { t } = useTranslation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = $api.useMutation("post", "/api/v1/auth/login", {
    onSuccess: (answer) => {
      if (answer.next_step === "totp") {
        onTotp();
      } else {
        onLoggedIn(); // first login: no TOTP yet
      }
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    login.mutate({ body: { username, password } });
  }

  return (
    <form onSubmit={submit}>
      <Stack>
        <TextInput
          label={t("login.username")}
          value={username}
          onChange={(event) => setUsername(event.currentTarget.value)}
          autoComplete="username"
          required
          data-autofocus
        />
        <PasswordInput
          label={t("login.password")}
          value={password}
          onChange={(event) => setPassword(event.currentTarget.value)}
          autoComplete="current-password"
          required
        />
        {login.isError && <Alert color="red">{t(errorKey(login.error))}</Alert>}
        <Button type="submit" loading={login.isPending}>
          {t("login.submit")}
        </Button>
      </Stack>
    </form>
  );
}

type TotpStepProps = {
  onBack: () => void;
  onLoggedIn: () => void;
};

function TotpStep({ onBack, onLoggedIn }: TotpStepProps) {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const [incomplete, setIncomplete] = useState(false);
  const verify = $api.useMutation("post", "/api/v1/auth/totp", { onSuccess: onLoggedIn });

  function submit(event: FormEvent) {
    event.preventDefault();
    const valid = CODE_PATTERN.test(code);
    setIncomplete(!valid);
    if (valid) {
      verify.mutate({ body: { code } });
    }
  }

  return (
    <form onSubmit={submit}>
      <Stack>
        <Text size="sm">{t("login.totpHelp")}</Text>
        <CodeInput label={t("login.totpCode")} value={code} onChange={setCode} />
        {incomplete && <Alert color="red">{t("login.codeFormat")}</Alert>}
        {verify.isError && <Alert color="red">{t(errorKey(verify.error))}</Alert>}
        <Button type="submit" loading={verify.isPending}>
          {t("login.totpSubmit")}
        </Button>
        <Button variant="subtle" onClick={onBack}>
          {t("login.otherAccount")}
        </Button>
      </Stack>
    </form>
  );
}
