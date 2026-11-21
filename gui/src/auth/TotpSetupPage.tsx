// First login, step 2: two-factor authentication. The controller gives a new
// secret and its otpauth:// address, shown as a QR code for the
// authenticator app; nothing is stored until a first code is confirmed.
import { Alert, Button, Center, Code, Loader, Stack, Text } from "@mantine/core";
import { useQueryClient } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { $api } from "../api/client";
import { errorKey } from "../api/errors";
import { AuthLayout } from "./AuthLayout";
import { CODE_PATTERN, CodeInput } from "./CodeInput";
import { refreshCurrentUser } from "./currentUser";
import { useLogout } from "./useLogout";

/** "JBSWY3DPEHPK3PXP…" -> "JBSW Y3DP EHPK 3PXP…", easier to type by hand. */
export function groupSecret(secret: string): string {
  return secret.match(/.{1,4}/g)?.join(" ") ?? secret;
}

export function TotpSetupPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const logout = useLogout();
  const [code, setCode] = useState("");
  const [incomplete, setIncomplete] = useState(false);
  // A POST, but asked once and kept: a new secret at each render or each
  // return to the window would change the QR code while it is being scanned.
  const setup = $api.useQuery("post", "/api/v1/auth/totp/setup", {}, {
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const confirm = $api.useMutation("post", "/api/v1/auth/totp/confirm", {
    onSuccess: () => refreshCurrentUser(queryClient),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    setIncomplete(!CODE_PATTERN.test(code));
    if (setup.data !== undefined && CODE_PATTERN.test(code)) {
      confirm.mutate({ body: { secret: setup.data.secret, code } });
    }
  }

  return (
    <AuthLayout title={t("totpSetup.title")}>
      <Text size="sm">{t("totpSetup.intro")}</Text>
      {setup.isPending && (
        <Center>
          <Loader />
        </Center>
      )}
      {setup.isError && <Alert color="red">{t(errorKey(setup.error))}</Alert>}
      {setup.data !== undefined && (
        <form onSubmit={submit}>
          <Stack>
            <Center>
              <QRCodeSVG value={setup.data.otpauth_uri} title={t("totpSetup.qrTitle")} size={200} />
            </Center>
            <Text size="sm">{t("totpSetup.manual")}</Text>
            <Code block>{groupSecret(setup.data.secret)}</Code>
            <CodeInput label={t("totpSetup.code")} value={code} onChange={setCode} />
            {incomplete && <Alert color="red">{t("login.codeFormat")}</Alert>}
            {confirm.isError && <Alert color="red">{t(errorKey(confirm.error))}</Alert>}
            <Button type="submit" loading={confirm.isPending}>
              {t("totpSetup.submit")}
            </Button>
          </Stack>
        </form>
      )}
      <Button variant="subtle" onClick={() => logout.mutate()}>
        {t("common.logout")}
      </Button>
    </AuthLayout>
  );
}
