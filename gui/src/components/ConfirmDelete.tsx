// "Delete" button that asks for a confirmation in a window, then calls
// onConfirm. A refusal of the controller (for example a site that still has
// routers) is shown in the window.
import { Button, Group, Modal, Stack, Text } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { ErrorAlert } from "./common";

type ConfirmDeleteProps = {
  /** Text of the button and title of the window. */
  label: string;
  /** What will be deleted, in a sentence. */
  message: string;
  onConfirm: () => Promise<unknown>;
  /** Called after a successful deletion. */
  onDeleted?: () => void;
  compact?: boolean;
};

export function ConfirmDelete({ label, message, onConfirm, onDeleted, compact }: ConfirmDeleteProps) {
  const { t } = useTranslation();
  const [opened, modal] = useDisclosure(false);
  const deletion = useMutation({
    mutationFn: onConfirm,
    onSuccess: () => {
      modal.close();
      onDeleted?.();
    },
  });

  function close() {
    deletion.reset();
    modal.close();
  }

  return (
    <>
      <Button color="red" variant="light" size={compact ? "xs" : "sm"} onClick={modal.open}>
        {label}
      </Button>
      <Modal opened={opened} onClose={close} title={label}>
        <Stack>
          <Text>{message}</Text>
          {deletion.isError && <ErrorAlert error={deletion.error} />}
          <Group justify="flex-end">
            <Button variant="default" onClick={close}>
              {t("common.cancel")}
            </Button>
            <Button color="red" loading={deletion.isPending} onClick={() => deletion.mutate()}>
              {t("common.delete")}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}
