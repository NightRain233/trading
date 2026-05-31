function formatDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function getDefaultHistoryStartDate(today = new Date()) {
  const year = today.getFullYear() - 5;
  const month = today.getMonth();
  const day = today.getDate();
  const candidate = new Date(year, month, day);

  if (candidate.getFullYear() !== year || candidate.getMonth() !== month) {
    return formatDate(new Date(year, month + 1, 0));
  }

  return formatDate(candidate);
}
