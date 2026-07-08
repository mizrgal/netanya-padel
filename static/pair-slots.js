document.querySelectorAll('.slot').forEach(function (slot) {
  var modeInput = slot.querySelector('input[name$="_mode"]');
  var buttons = slot.querySelectorAll('.mode-btn');
  buttons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      buttons.forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
      var mode = btn.dataset.mode;
      modeInput.value = mode;
      slot.querySelectorAll('.slot-fields').forEach(function (f) {
        f.classList.toggle('active', f.dataset.modeFields === mode);
      });
    });
  });

  var searchInput = slot.querySelector('.user-search');
  if (searchInput) {
    var resultsBox = slot.querySelector('.search-results');
    var hiddenId = slot.querySelector('input[name$="_user_id"]');
    var hint = slot.querySelector('.selected-user-hint');
    var debounceTimer;
    searchInput.addEventListener('input', function () {
      hiddenId.value = '';
      hint.textContent = '';
      clearTimeout(debounceTimer);
      var q = searchInput.value.trim();
      if (q.length < 2) {
        resultsBox.classList.remove('active');
        resultsBox.innerHTML = '';
        return;
      }
      debounceTimer = setTimeout(function () {
        fetch('/api/users/search?q=' + encodeURIComponent(q))
          .then(function (r) { return r.json(); })
          .then(function (users) {
            resultsBox.innerHTML = '';
            if (!users.length) {
              resultsBox.classList.remove('active');
              return;
            }
            users.forEach(function (u) {
              var item = document.createElement('div');
              item.className = 'search-result-item';
              item.textContent = u.username + ' (' + u.phone + ')';
              item.addEventListener('click', function () {
                hiddenId.value = u.id;
                searchInput.value = u.username;
                hint.textContent = 'נבחר/ה: ' + u.username;
                resultsBox.classList.remove('active');
                resultsBox.innerHTML = '';
              });
              resultsBox.appendChild(item);
            });
            resultsBox.classList.add('active');
          });
      }, 250);
    });
  }
});
