// A button that opens a window (usually a form). The content receives
// ``close`` to close the window once its work is done.
import { Button, Modal, type ButtonProps } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import type { ReactNode } from "react";

type ModalButtonProps = {
  label: string;
  title: string;
  children: (close: () => void) => ReactNode;
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
};

export function ModalButton({ label, title, children, variant, size }: ModalButtonProps) {
  const [opened, modal] = useDisclosure(false);
  return (
    <>
      <Button variant={variant} size={size} onClick={modal.open}>
        {label}
      </Button>
      <Modal opened={opened} onClose={modal.close} title={title}>
        {opened && children(modal.close)}
      </Modal>
    </>
  );
}
