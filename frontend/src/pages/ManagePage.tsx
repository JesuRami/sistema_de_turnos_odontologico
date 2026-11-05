import ManageFlow from "../features/manage/ManageFlow";

/** Ruta pública `/g/:token` (C-08): solo compone; el flujo vive en `features/manage`. */
function ManagePage(): JSX.Element {
  return <ManageFlow />;
}

export default ManagePage;
