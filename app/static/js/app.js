document.addEventListener('DOMContentLoaded', () => {
  const buttons = document.querySelectorAll('button');
  buttons.forEach((button) => {
    button.addEventListener('click', () => {
      button.classList.add('transition-all', 'duration-200');
    });
  });

  document.body.addEventListener('caurisTransferDeleted', (event) => {
    const transactionIds = event.detail && event.detail.ids;
    if (!Array.isArray(transactionIds)) return;
    transactionIds.forEach((transactionId) => {
      const transaction = document.getElementById(`transaction-${transactionId}`);
      if (transaction) transaction.remove();
    });
  });
});
