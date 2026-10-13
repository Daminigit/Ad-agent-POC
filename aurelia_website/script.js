/**
 * AURELIA HEIGHTS — INTERACTIVE LOGIC
 */

document.addEventListener('DOMContentLoaded', () => {
  // ── 1. Sticky Header Blur ─────────────────────────
  const header = document.querySelector('.header');
  window.addEventListener('scroll', () => {
    if (window.scrollY > 40) {
      header.classList.add('scrolled');
    } else {
      header.classList.remove('scrolled');
    }
  });

  // ── 2. Mobile Nav Toggle ──────────────────────────
  const mobileToggle = document.getElementById('mobileToggle');
  const navMenu = document.getElementById('navMenu');
  if (mobileToggle && navMenu) {
    mobileToggle.addEventListener('click', () => {
      navMenu.classList.toggle('open');
      mobileToggle.textContent = navMenu.classList.contains('open') ? '✕' : '☰';
    });
    navMenu.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', () => {
        navMenu.classList.remove('open');
        mobileToggle.textContent = '☰';
      });
    });
  }

  // ── 3. Reel Sound Toggle & Play ───────────────────
  const reelVideo = document.getElementById('reelVideo');
  const reelSoundBtn = document.getElementById('reelSoundBtn');
  if (reelVideo && reelSoundBtn) {
    reelSoundBtn.addEventListener('click', () => {
      if (reelVideo.muted) {
        reelVideo.muted = false;
        reelSoundBtn.innerHTML = '🔊';
        reelSoundBtn.title = 'Mute Audio';
      } else {
        reelVideo.muted = true;
        reelSoundBtn.innerHTML = '🔇';
        reelSoundBtn.title = 'Unmute Voiceover';
      }
    });
  }

  // ── 4. Unit Configurations Tab Switcher ───────────
  const unitData = {
    '2bhk': {
      title: '2 BHK Luxury Residence',
      price: '₹96 Lakhs – ₹1.08 Crore',
      carpet: '820 sq.ft.',
      saleable: '1,140 sq.ft.',
      balconies: '1 Wide Deck (14\'0" × 5\'0")',
      toilets: '2 Bathrooms',
      facing: 'East / North Garden View',
      dimensions: ['Living: 18\'0" × 15\'0"', 'Master Bed: 13\'0" × 12\'0"', 'Bed 2: 12\'0" × 11\'0"', 'Kitchen: 9\'0" × 8\'6"'],
      availability: 'Available (Tower A & B)',
      ctaText: 'Enquire for 2 BHK'
    },
    '3bhk': {
      title: '3 BHK Royal Residence',
      price: '₹1.42 Crore – ₹1.58 Crore',
      carpet: '1,210 sq.ft.',
      saleable: '1,680 sq.ft.',
      balconies: '1 Panoramic Deck + Utility',
      toilets: '3 Bathrooms',
      facing: 'North-East Clubhouse Facing',
      dimensions: ['Living: 21\'0" × 16\'0"', 'Master Suite: 14\'0" × 12\'6"', 'Bed 2: 12\'0" × 11\'0"', 'Bed 3: 12\'0" × 11\'0"', 'Kitchen + Utility: 16\'0" × 9\'0"'],
      availability: 'Fast Selling (Tower B & C)',
      ctaText: 'Enquire for 3 BHK'
    },
    '4bhk': {
      title: '4 BHK Grand Penthouse Suite',
      price: '₹1.95 Crore – ₹2.10 Crore',
      carpet: '1,650 sq.ft.',
      saleable: '2,250 sq.ft.',
      balconies: 'Wrap-around Balcony (18\'0" × 6\'0")',
      toilets: '4 Luxury Bathrooms',
      facing: 'Unobstructed Sky Deck Views',
      dimensions: ['Living/Dining: 24\'0" × 17\'0"', 'Master Bed: 15\'0" × 13\'0"', 'Bed 2: 12\'6" × 11\'6"', 'Bed 3: 12\'0" × 11\'0"', 'Bed 4: 12\'0" × 11\'6"'],
      availability: 'Phase 1 Sold Out (Join Waitlist)',
      ctaText: 'Join Phase 2 Waitlist'
    }
  };

  const tabButtons = document.querySelectorAll('.tab-btn');
  const cfgTitle = document.getElementById('cfgTitle');
  const cfgPrice = document.getElementById('cfgPrice');
  const cfgCarpet = document.getElementById('cfgCarpet');
  const cfgSaleable = document.getElementById('cfgSaleable');
  const cfgBalconies = document.getElementById('cfgBalconies');
  const cfgToilets = document.getElementById('cfgToilets');
  const cfgFacing = document.getElementById('cfgFacing');
  const cfgAvailability = document.getElementById('cfgAvailability');
  const cfgDimensions = document.getElementById('cfgDimensions');
  const cfgCta = document.getElementById('cfgCta');

  tabButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      tabButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      const key = btn.dataset.unit;
      const data = unitData[key];
      if (!data) return;

      cfgTitle.textContent = data.title;
      cfgPrice.textContent = data.price;
      cfgCarpet.textContent = data.carpet;
      cfgSaleable.textContent = data.saleable;
      cfgBalconies.textContent = data.balconies;
      cfgToilets.textContent = data.toilets;
      cfgFacing.textContent = data.facing;
      cfgAvailability.textContent = data.availability;
      cfgCta.textContent = data.ctaText;

      cfgDimensions.innerHTML = '';
      data.dimensions.forEach(dim => {
        const chip = document.createElement('span');
        chip.className = 'dimension-chip';
        chip.textContent = dim;
        cfgDimensions.appendChild(chip);
      });
    });
  });

  // ── 5. Interactive EMI Calculator ─────────────────
  const loanInput = document.getElementById('loanAmount');
  const rateInput = document.getElementById('interestRate');
  const tenureInput = document.getElementById('loanTenure');

  const loanVal = document.getElementById('loanAmountVal');
  const rateVal = document.getElementById('interestRateVal');
  const tenureVal = document.getElementById('loanTenureVal');

  const emiResult = document.getElementById('emiResult');
  const totalInterestEl = document.getElementById('totalInterest');
  const totalPayableEl = document.getElementById('totalPayable');

  function updateEMI() {
    const P = parseFloat(loanInput.value) * 100000; // in Rupees
    const annualRate = parseFloat(rateInput.value);
    const r = (annualRate / 12) / 100; // monthly rate
    const n = parseFloat(tenureInput.value) * 12; // months

    loanVal.textContent = `₹${loanInput.value} Lakhs`;
    rateVal.textContent = `${rateInput.value}%`;
    tenureVal.textContent = `${tenureInput.value} Yrs`;

    // EMI Formula: [P x r x (1+r)^n] / [(1+r)^n - 1]
    const emi = (P * r * Math.pow(1 + r, n)) / (Math.pow(1 + r, n) - 1);
    const totalPayment = emi * n;
    const totalInterest = totalPayment - P;

    emiResult.textContent = `₹${Math.round(emi).toLocaleString('en-IN')}`;
    totalInterestEl.textContent = `₹${(totalInterest / 100000).toFixed(1)} Lakhs`;
    totalPayableEl.textContent = `₹${(totalPayment / 100000).toFixed(1)} Lakhs`;
  }

  if (loanInput && rateInput && tenureInput) {
    loanInput.addEventListener('input', updateEMI);
    rateInput.addEventListener('input', updateEMI);
    tenureInput.addEventListener('input', updateEMI);
    updateEMI();
  }

  // ── 6. VIP Tour Booking Form & Confirmation Modal ─
  const bookingForm = document.getElementById('bookingForm');
  const confirmModal = document.getElementById('confirmModal');
  const modalClose = document.getElementById('modalClose');
  const modalLeadName = document.getElementById('modalLeadName');

  if (bookingForm) {
    bookingForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const name = document.getElementById('leadName').value.trim();
      const phone = document.getElementById('leadPhone').value.trim();
      const unit = document.getElementById('leadUnit').value;

      if (!name || !phone) {
        alert('Please fill in your name and phone number.');
        return;
      }

      if (modalLeadName) modalLeadName.textContent = name;
      if (confirmModal) confirmModal.classList.add('active');
      bookingForm.reset();
    });
  }

  if (modalClose && confirmModal) {
    modalClose.addEventListener('click', () => {
      confirmModal.classList.remove('active');
    });
    confirmModal.addEventListener('click', (e) => {
      if (e.target === confirmModal) {
        confirmModal.classList.remove('active');
      }
    });
  }

  // ── 7. Video Modal for Full Landscape Walkthrough ──
  const openVideoBtn = document.getElementById('openVideoBtn');
  const videoModal = document.getElementById('videoModal');
  const videoClose = document.getElementById('videoClose');
  const modalVideoPlayer = document.getElementById('modalVideoPlayer');

  if (openVideoBtn && videoModal) {
    openVideoBtn.addEventListener('click', (e) => {
      e.preventDefault();
      videoModal.classList.add('active');
      if (modalVideoPlayer) modalVideoPlayer.play();
    });
  }

  if (videoClose && videoModal) {
    const closeVideo = () => {
      videoModal.classList.remove('active');
      if (modalVideoPlayer) modalVideoPlayer.pause();
    };
    videoClose.addEventListener('click', closeVideo);
    videoModal.addEventListener('click', (e) => {
      if (e.target === videoModal) closeVideo();
    });
  }
});
